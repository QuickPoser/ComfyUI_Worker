import logging
import queue
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Optional, Tuple
import gzip
import io

import env

import grpc
import requests

from comfygw_proto import http_tunnel_pb2, http_tunnel_pb2_grpc, utils_pb2
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

# 常量定义
class TunnelConstants:
    DEFAULT_TIMEOUT = 120
    CHUNK_SIZE = 64 * 1024  # 64KB
    MAX_COMPRESS_SIZE = 50 * 1024 * 1024  # 50MB
    COMPRESSION_THRESHOLD = 0.9  # 压缩率阈值
    
    COMPRESSIBLE_TYPES = [
        'text/', 'application/json', 'application/xml', 'application/javascript',
        'application/css', 'image/svg+xml', 'application/wasm'
    ]
    
    EXCLUDED_HEADERS = ["Origin", "Host", "Connection", "Content-Length"]


class TunnelStopped(Exception):
    """自定义异常，用于表示隧道已停止"""
    pass


class ResponseCompressor:
    """响应压缩处理器"""
    
    @staticmethod
    def should_compress(resp, content_length: int = None) -> bool:
        """判断响应是否应该被压缩"""
        # 如果已经被压缩过了，不再压缩
        if resp.headers.get('Content-Encoding') in ['gzip', 'deflate', 'br']:
            return False
        
        # 获取内容长度
        if content_length is None:
            content_length_str = resp.headers.get('Content-Length')
            if content_length_str:
                try:
                    content_length = int(content_length_str)
                except ValueError:
                    content_length = 0
        
        # 只压缩指定大小以内的内容
        if content_length and content_length > TunnelConstants.MAX_COMPRESS_SIZE:
            return False
        
        # 判断内容类型是否适合压缩
        content_type = resp.headers.get('Content-Type', '').lower()
        return any(content_type.startswith(comp_type) 
                  for comp_type in TunnelConstants.COMPRESSIBLE_TYPES)
    
    @staticmethod
    def compress_content(content: bytes) -> Tuple[bytes, dict]:
        """压缩内容并返回压缩后的数据和更新的headers"""
        if not content:
            return content, {}
            
        compressed_buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=compressed_buffer, mode='wb') as gz:
            gz.write(content)
        
        compressed_data = compressed_buffer.getvalue()
        compression_ratio = len(compressed_data) / len(content)
        
        # 如果压缩率不好，不使用压缩
        if compression_ratio > TunnelConstants.COMPRESSION_THRESHOLD:
            return content, {}
        
        updated_headers = {
            'Content-Encoding': 'gzip',
            'Content-Length': str(len(compressed_data))
        }
        
        return compressed_data, updated_headers


class StreamingChunkIterator:
    """流式数据块迭代器，用于实时传递请求体数据"""

    def __init__(self, timeout: int = 30):
        self.q = queue.Queue()
        self._closed = False
        self._lock = threading.RLock()
        self._timeout = timeout

    def write_chunk(self, chunk: bytes):
        with self._lock:
            if not self._closed:
                self.q.put(chunk)

    def close(self):
        with self._lock:
            self._closed = True
            self.q.put(None)  # 结束标志

    def __iter__(self):
        return self

    def __next__(self):
        try:
            chunk = self.q.get(timeout=self._timeout)
            if chunk is None:  # 流结束
                raise StopIteration
            return chunk
        except queue.Empty:
            if self._closed:
                raise StopIteration
            raise

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed


class TunnelRequest:
    """处理单个流式请求的辅助类，包含响应处理逻辑"""

    def __init__(
        self,
        req_id: str,
        header_chunk: http_tunnel_pb2.HttpRequest,
        backend_address: str,
        send_response: Callable,
        finish_request: Callable,
        executor: ThreadPoolExecutor,
    ):
        self.req_id = req_id
        self._lock = threading.Lock()
        self._backend_address = backend_address
        self._send_response = send_response
        self._finish_request = finish_request
        self._chunk_iterator: Optional[StreamingChunkIterator] = None
        self._executor = executor
        self._start_time = time.time()
        self._timeout = TunnelConstants.DEFAULT_TIMEOUT
        self._expect_chunk_index = 1
        self._header_chunk = header_chunk
        self._aborted = threading.Event()

        self._initialize_chunk_iterator(header_chunk)
        
    def _initialize_chunk_iterator(self, header_chunk):
        """初始化数据块迭代器"""
        body = getattr(header_chunk, "body", b"")
        has_body = len(body) > 0
        is_final = header_chunk.isFinalChunk

        if has_body or not is_final:
            self._chunk_iterator = StreamingChunkIterator(timeout=self._timeout)
            if has_body:
                self._chunk_iterator.write_chunk(body)
            if is_final:
                self._chunk_iterator.close()
        
    def start(self):
        """启动请求处理"""
        self._executor.submit(
            self.process_streaming_request, self._chunk_iterator, self._header_chunk
        )

    def add_chunk(self, chunk):
        """添加数据块"""
        # 检查请求是否超时
        if time.time() - self._start_time > self._timeout:
            logger.warning(f"[{self.req_id}] Request timeout, dropping chunk")
            return

        if self._chunk_iterator is None or self._chunk_iterator.closed:
            logger.warning(f"[{self.req_id}] Chunk iterator is closed, ignoring chunk")
            return

        if chunk.chunkIndex != self._expect_chunk_index:
            logger.warning(
                f"[{self.req_id}] Chunk index mismatch: expected {self._expect_chunk_index}, got {chunk.chunkIndex}"
            )
            return

        # 实时写入数据块，不缓存
        self._chunk_iterator.write_chunk(chunk.body)
        self._expect_chunk_index += 1
        if chunk.isFinalChunk:
            self._chunk_iterator.close()

    def abort(self):
        """中断请求，不再发送任何 response"""
        self._aborted.set()
        if self._chunk_iterator is not None:
            self._chunk_iterator.close()

    def process_streaming_request(
        self, chunk_iterator: StreamingChunkIterator, header_chunk
    ):
        """处理流式请求"""
        url = None
        try:
            req_id = self.req_id
            method = header_chunk.method
            path = getattr(header_chunk, "path", "")
            headers = dict(header_chunk.headers or {})
            url = f"{self._backend_address}{path}"

            logger.info(f"[{req_id}] process_streaming_request: method={method}, url={url}")
            
            # 清理不需要的头部
            for key in TunnelConstants.EXCLUDED_HEADERS:
                headers.pop(key, None)

            # 发送HTTP请求并处理响应
            with requests.Session() as session:
                adapter = HTTPAdapter(max_retries=2, pool_connections=10, pool_maxsize=20)
                session.mount("http://", adapter)
                session.mount("https://", adapter)

                request_kwargs = {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "timeout": (5, 60),
                    "stream": True,
                }
                if chunk_iterator is not None:
                    request_kwargs["data"] = chunk_iterator

                start_time = time.time()
                with session.request(**request_kwargs) as resp:
                    if self._aborted.is_set():
                        return
                    
                    # 判断是否压缩处理
                    content_length = resp.headers.get('Content-Length')
                    should_compress = ResponseCompressor.should_compress(
                        resp, int(content_length) if content_length else None
                    )
                    
                    if should_compress:
                        self._handle_compressed_response(resp, url, start_time)
                    else:
                        self._handle_streaming_response(resp, url, start_time)
                        
        except Exception as e:
            if not self._aborted.is_set():
                logger.error(
                    f"[{self.req_id}] HTTP error: {e}, url={url}\n{traceback.format_exc()}"
                )
                self._send_error_response(500, str(e).encode())
        finally:
            self._finish_request(self.req_id)

    def _handle_compressed_response(self, resp, url: str, start_time: float):
        """处理压缩响应"""
        # 读取全部内容到内存
        content = resp.content

        if self._aborted.is_set():
            return

        # 尝试压缩
        compressed_content, compression_headers = ResponseCompressor.compress_content(content)

        # 准备响应头
        response_headers = self._prepare_headers(resp.headers, compression_headers)

        # 分块发送压缩后的内容
        chunk_size = TunnelConstants.CHUNK_SIZE
        total_size = len(compressed_content)
        chunk_index = 0
        offset = 0
        headers_sent = False

        while offset < total_size:
            if self._aborted.is_set():
                return

            # 获取当前块
            end_offset = min(offset + chunk_size, total_size)
            chunk_data = compressed_content[offset:end_offset]
            is_final = (end_offset >= total_size)

            response = http_tunnel_pb2.HttpResponse(
                requestId=self.req_id,
                statusCode=resp.status_code,
                headers=response_headers if not headers_sent else [],
                body=chunk_data,
                isFinalChunk=is_final,
                chunkIndex=chunk_index,
                chunkOffset=offset,
            )

            self._send_response(response)
            headers_sent = True
            chunk_index += 1
            offset = end_offset

        # 如果内容为空，发送一个空的最终块
        if total_size == 0:
            response = http_tunnel_pb2.HttpResponse(
                requestId=self.req_id,
                statusCode=resp.status_code,
                headers=response_headers,
                body=b"",
                isFinalChunk=True,
                chunkIndex=0,
                chunkOffset=0,
            )
            self._send_response(response)

        self._log_completion(
            "Compressed", resp.status_code, start_time, 
            len(content), len(compressed_content), url, chunk_index
        )

    def _handle_streaming_response(self, resp, url: str, start_time: float):
        """处理流式响应"""
        chunk_index = 0
        total_sent = 0
        headers_sent = False

        for chunk_data in resp.iter_content(chunk_size=TunnelConstants.CHUNK_SIZE):
            if self._aborted.is_set():
                return
            if not chunk_data:
                continue

            response = http_tunnel_pb2.HttpResponse(
                requestId=self.req_id,
                statusCode=resp.status_code,
                headers=list(resp.headers.items()) if not headers_sent else [],
                body=chunk_data,
                isFinalChunk=False,
                chunkIndex=chunk_index,
                chunkOffset=total_sent,
            )

            self._send_response(response)
            headers_sent = True
            chunk_index += 1
            total_sent += len(chunk_data)

        if not self._aborted.is_set():
            # 发送最终块
            self._send_final_chunk(resp.status_code, chunk_index, total_sent)
            self._log_completion(
                "Streaming", resp.status_code, start_time, 
                total_sent, total_sent, url, chunk_index + 1
            )
                
    def _prepare_headers(self, original_headers, compression_headers: dict) -> list:
        """准备响应头"""
        response_headers = list(original_headers.items())
        
        if compression_headers:
            # 移除冲突的头部
            response_headers = [
                (k, v) for k, v in response_headers 
                if k.lower() not in ['content-length', 'content-encoding']
            ]
            response_headers.extend(compression_headers.items())
        
        return response_headers
    
    def _send_final_response(self, status_code: int, headers: list, body: bytes):
        """发送最终响应"""
        response = http_tunnel_pb2.HttpResponse(
            requestId=self.req_id,
            statusCode=status_code,
            headers=headers,
            body=body,
            isFinalChunk=True,
            chunkIndex=0,
            chunkOffset=0,
        )
        self._send_response(response)
    
    def _send_final_chunk(self, status_code: int, chunk_index: int, total_sent: int):
        """发送最终数据块"""
        final_response = http_tunnel_pb2.HttpResponse(
            requestId=self.req_id,
            statusCode=status_code,
            headers=[],
            body=b"",
            isFinalChunk=True,
            chunkIndex=chunk_index,
            chunkOffset=total_sent,
        )
        self._send_response(final_response)
    
    def _send_error_response(self, status_code: int, body: bytes):
        """发送错误响应"""
        response = http_tunnel_pb2.HttpResponse(
            requestId=self.req_id,
            statusCode=status_code,
            headers=[],
            body=body,
            isFinalChunk=True,
            chunkIndex=0,
            chunkOffset=0,
        )
        try:
            self._send_response(response, 5.0)
        except TunnelStopped:
            logger.warning(f"[{self.req_id}] Tunnel stopped while sending error response")
        except Exception as e:
            logger.error(f"[{self.req_id}] Error sending error response: {e}", exc_info=True)
    
    def _log_completion(self, response_type: str, status_code: int, start_time: float, 
                       original_size: int, final_size: int, url: str, chunks: int = None):
        """记录完成日志"""
        cost = time.time() - start_time
        chunks_info = f", chunks={chunks}" if chunks else ""
        
        # 计算压缩率
        compression_ratio_info = ""
        if original_size > 0 and final_size != original_size:
            compression_ratio = final_size / original_size
            compression_ratio_info = f", compression_ratio={compression_ratio:.2f}"
        
        logger.info(
            f"[TunnelRequest][{self.req_id}] {response_type} response completed: "
            f"status={status_code}, time={cost:.2f}s, "
            f"original_size={original_size}, final_size={final_size}{compression_ratio_info}{chunks_info}, url={url}"
        )


class TunnelClient:
    def __init__(
        self,
        server_address: str,
        backend_address: str,
        max_workers: int = 32,  # 减少并发数以节省内存
    ):
        self.server_address = server_address
        self.backend_address = backend_address
        self.channel = None
        self.stub = None
        self.stream = None
        self._response_queue = queue.Queue(maxsize=1024)  # 减少队列大小
        self._stop_event = threading.Event()
        self._request_thread = None
        self._chunk_buffer: Dict[str, TunnelRequest] = {}
        self._chunk_buffer_lock = threading.Lock()  # 新增锁
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="tunnel-worker"
        )
        self._last_cleanup = time.time()

    def run(self):
        with grpc.insecure_channel(self.server_address) as self.channel:
            self.stub = http_tunnel_pb2_grpc.HttpTunnelStub(self.channel)
            self.stream = self.stub.StartTunnel(self._message_generator())

            try:
                msg = next(self.stream)  # 发送认证消息
                if not msg.HasField("authRsp"):
                    raise Exception("Authentication failed, no authRsp in response")

                auth_rsp = msg.authRsp
                if not auth_rsp.ok:
                    raise Exception(f"Authentication failed: {auth_rsp.errorMsg}")
                
                logger.info(
                    f"TunnelClient started at {self.server_address}, sessionId={env.session_id}"
                )

                for msg in self.stream:
                    if msg.HasField("request"):
                        req = msg.request
                        req_id = req.requestId
                        chunk_index = getattr(req, "chunkIndex", 0)

                        if chunk_index == 0:
                            with self._chunk_buffer_lock:
                                if req_id in self._chunk_buffer:
                                    # 如果已经存在，说明是一个新的请求，清理旧的
                                    logger.warning(
                                        f"Duplicate requestId {req_id} received, replacing old request"
                                    )
                                    continue

                                tunnel_req = TunnelRequest(
                                    req_id=req_id,
                                    header_chunk=req,
                                    backend_address=self.backend_address,
                                    send_response=self.send_response,
                                    finish_request=self.finish_request,
                                    executor=self._executor,
                                )
                                tunnel_req.start()
                                self._chunk_buffer[req_id] = tunnel_req

                        if chunk_index > 0:
                            with self._chunk_buffer_lock:
                                if req_id not in self._chunk_buffer:
                                    logger.warning(
                                        f"Received chunk for unknown requestId {req_id}, ignoring"
                                    )
                                    continue

                                self._chunk_buffer[req_id].add_chunk(req)

                    elif msg.HasField("abort"):
                        abort_msg = msg.abort
                        req_id = abort_msg.requestId
                        with self._chunk_buffer_lock:
                            if req_id in self._chunk_buffer:
                                logger.info(
                                    f"Aborting request {req_id}: {abort_msg.reason}"
                                )
                                self._chunk_buffer[req_id].abort()  # 调用 abort
                                del self._chunk_buffer[req_id]
                            else:
                                logger.warning(
                                    f"Abort received for unknown requestId {req_id}"
                                )

            except Exception as e:
                logger.error(f"Error in tunnel stream: {e}", exc_info=True)

            self._stop_event.set()
            self._executor.shutdown(wait=False)

    def _message_generator(self):
        # 1. 发送认证消息
        auth_msg = http_tunnel_pb2.TunnelMessage(
            authReq=utils_pb2.AuthReq(
                accessToken=env.taskq_access_key,
                sessionId=env.session_id,
                hostName=env.hostname,
                group=env.taskq_group,
            )
        )
        yield auth_msg

        # 心跳计时器
        last_heartbeat = time.time()
        heartbeat_interval = 5  # 5秒发送一次心跳

        # 2. 持续发送请求和心跳（通过队列驱动）
        while not self._stop_event.is_set():
            try:
                # 检查是否需要发送心跳
                current_time = time.time()
                if current_time - last_heartbeat >= heartbeat_interval:
                    heartbeat_msg = http_tunnel_pb2.TunnelMessage(
                        heartbeat=utils_pb2.Heartbeat()
                    )
                    yield heartbeat_msg
                    last_heartbeat = current_time

                # 处理响应消息
                resp = self._response_queue.get(timeout=0.1)
                yield http_tunnel_pb2.TunnelMessage(response=resp)
            except queue.Empty:
                continue

    # 这个是 请求从自己的 工作线程里调用的
    def send_response(self, response, timeout: float = 5.0):
        if self._stop_event.is_set():
            raise TunnelStopped()
        self._response_queue.put(response, timeout)

    def finish_request(self, req_id: str):
        """完成请求，清理相关资源"""
        with self._chunk_buffer_lock:
            if req_id in self._chunk_buffer:
                del self._chunk_buffer[req_id]


class TunnelService:
    """简化设计：这个服务启动后不会停止，没有 stop 方法"""

    def __init__(
        self,
        server_address: str,
        backend_address: str,
        max_workers: int = 32,
        reconnect_interval: int = 5,
    ):
        self.server_address = server_address
        self.backend_address = backend_address
        self.max_workers = max_workers
        self.reconnect_interval = reconnect_interval
        self._client: Optional[TunnelClient] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self.run, daemon=True, name="TunnelClientThread"
        )
        self._thread.start()

    def run(self):
        while True:
            try:
                self._client = TunnelClient(
                    backend_address=self.backend_address,
                    server_address=self.server_address,
                    max_workers=self.max_workers,
                )
                self._client.run()
            except Exception as e:
                logger.exception(f"TunnelClient error: {e}")
            else:
                logger.info("TunnelClient stopped gracefully")

            logger.info(f"TunnelClient retrying in {self.reconnect_interval}s...")
            time.sleep(self.reconnect_interval)
