import env
import os
import torch
import datetime
import grpc
import hashlib
import folder_paths
from io import BytesIO
from comfygw_proto import taskq_pb2, taskq_pb2_grpc
import numpy as np
import folder_paths
from PIL import Image, ImageOps, ImageSequence
import mimetypes
from comfy_extras import nodes_audio, nodes_video


from comfy.cli_args import args
import nodes
import node_helpers

def download_file(file_id):
    """
    下载文件到本地 input_dir/objects/xx/xx/hash，并建立软链接到 input_dir/file_id。
    如果文件已存在则直接返回软链接路径。
    """
    input_dir = folder_paths.get_input_directory()
    temp_dir = folder_paths.get_temp_directory()

    # 1. 建立 gRPC 连接，获取文件流和元数据
    with grpc.insecure_channel(env.taskq_server_url) as grpc_channel:
        taskq_stub = taskq_pb2_grpc.TaskServiceStub(grpc_channel)
        stream = taskq_stub.DownloadFile(taskq_pb2.DownloadRequest(fileID=file_id))
        metadata = dict(stream.initial_metadata())
        file_id = metadata.get("file-id")
        file_hash = metadata.get("file-hash")
        if not file_id or not file_hash:
            raise RuntimeError("File not found or invalid file ID/hash.")

        # 2. 组织目标路径
        subdir1, subdir2 = file_hash[:2], file_hash[2:4]
        hash_path = os.path.join(input_dir, "objects", subdir1, subdir2, file_hash)
        id_path = os.path.join(input_dir, file_id)
        os.makedirs(os.path.dirname(hash_path), exist_ok=True)

        # 3. 如果 hash 文件已存在，建立软链接并返回
        if os.path.exists(hash_path):
            if not os.path.exists(id_path):
                try:
                    os.symlink(hash_path, id_path)
                except FileExistsError:
                    pass
            return id_path

        # 4. 下载文件到临时目录
        os.makedirs(temp_dir, exist_ok=True)
        tmp_path = os.path.join(
            temp_dir,
            f"{file_hash}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.downloading"
        )
        with open(tmp_path, "wb") as f:
            for msg in stream:
                f.write(msg.chunk)

        # 5. 移动到目标路径，并建立软链接
        os.rename(tmp_path, hash_path)
        if not os.path.exists(id_path):
            try:
                os.symlink(hash_path, id_path)
            except FileExistsError:
                pass

        return id_path

def download_image(file_id):
    file_path = download_file(file_id)
    return Image.open(file_path)


def upload_file(file_or_bytes, metadata=[], chunk_size=128*1024, type="output"):
    def get_chunks_from_bytes(content):
        for i in range(0, len(content), chunk_size):
            yield taskq_pb2.UploadRequest(chunk=content[i:i+chunk_size])

    def get_chunks_from_file(file_path):
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield taskq_pb2.UploadRequest(chunk=chunk)

    # 判断类型，避免一次性读取大文件
    if isinstance(file_or_bytes, bytes):
        chunks_generator = get_chunks_from_bytes(file_or_bytes)
    elif isinstance(file_or_bytes, str) and os.path.isfile(file_or_bytes):
        chunks_generator = get_chunks_from_file(file_or_bytes)
    else:
        raise ValueError("file_or_bytes must be bytes or a valid file path")

    with grpc.insecure_channel(env.taskq_server_url) as grpc_channel:
        taskq_stub = taskq_pb2_grpc.TaskServiceStub(grpc_channel)
        resp = taskq_stub.UploadFile(chunks_generator, metadata=metadata)
        return resp.fileID
    

def upload_image(
    context, image, filename_prefix, format="png", pnginfo=None, 
    compress_level=4, chunk_size=1024*1024, dpi=None
):
    with BytesIO() as output:
        image.save(output, format=format, pnginfo=pnginfo, compress_level=compress_level, dpi=dpi)
        contents = output.getvalue()

        return upload_file(
            contents,
            metadata=(
                ("access-token", env.taskq_access_key),
                ("file-name", f"{filename_prefix}_{datetime.datetime.now()}.{format.lower()}"),
                ("file-type", f"image/{format.lower()}"),
                ("output-type", "workflow"),
                ("task-context", context.json())
            ),
            chunk_size=chunk_size
        )    
    

def get_file_hash(file):
    input_dir = folder_paths.get_input_directory()
    file_path = os.path.join(input_dir, file)
    m = hashlib.sha256()
    with open(file_path, 'rb') as f:
        m.update(f.read())
    return m.digest().hex()

class LoadImage:
    @classmethod
    def INPUT_TYPES(s):
        return {"required":
                    {"image": ('STRING', {"image_upload": True})},
                }

    CATEGORY = "comfygw"
    DESCRIPTION = "ComfyGW: Load Image"

    RETURN_TYPES = ("IMAGE", "MASK", "FLOAT", "FLOAT")
    FUNCTION = "load_image"
    def load_image(self, image):
        image_file_id = image
        
        img = node_helpers.pillow(download_image, image_file_id)
        dpi = (0, 0)
        if "dpi" in img.info:
            dpi = img.info["dpi"]
        
        output_images = []
        output_masks = []
        w, h = None, None

        excluded_formats = ['MPO']
        
        for i in ImageSequence.Iterator(img):
            i = node_helpers.pillow(ImageOps.exif_transpose, i)

            if i.mode == 'I':
                i = i.point(lambda i: i * (1 / 255))
            image = i.convert("RGB")

            if len(output_images) == 0:
                w = image.size[0]
                h = image.size[1]
            
            if image.size[0] != w or image.size[1] != h:
                continue
            
            image = np.array(image).astype(np.float32) / 255.0
            image = torch.from_numpy(image)[None,]
            if 'A' in i.getbands():
                mask = np.array(i.getchannel('A')).astype(np.float32) / 255.0
                mask = 1. - torch.from_numpy(mask)
            else:
                mask = torch.zeros((64,64), dtype=torch.float32, device="cpu")
            output_images.append(image)
            output_masks.append(mask.unsqueeze(0))

        if len(output_images) > 1 and img.format not in excluded_formats:
            output_image = torch.cat(output_images, dim=0)
            output_mask = torch.cat(output_masks, dim=0)
        else:
            output_image = output_images[0]
            output_mask = output_masks[0]

        return (output_image, output_mask, dpi[0], dpi[1])

    @classmethod
    def IS_CHANGED(s, image):
        return get_file_hash(image)

    @classmethod
    def VALIDATE_INPUTS(s, image):
        return True


class LoadImageMask:
    _color_channels = ["alpha", "red", "green", "blue"]
    @classmethod
    def INPUT_TYPES(s):
        return {"required":
                    {"image": ('STRING', {"image_upload": True}),
                     "channel": (s._color_channels, ), }
                }

    CATEGORY = "comfygw"
    DESCRIPTION = "ComfyGW: Load Image Mask"

    RETURN_TYPES = ("MASK",)
    FUNCTION = "load_image"
    def load_image(self, image, channel):
        image_file_id = image
        i = node_helpers.pillow(download_image, image_file_id)
        i = node_helpers.pillow(ImageOps.exif_transpose, i)
        if i.getbands() != ("R", "G", "B", "A"):
            if i.mode == 'I':
                i = i.point(lambda i: i * (1 / 255))
            i = i.convert("RGBA")
        mask = None
        c = channel[0].upper()
        if c in i.getbands():
            mask = np.array(i.getchannel(c)).astype(np.float32) / 255.0
            mask = torch.from_numpy(mask)
            if c == 'A':
                mask = 1. - mask
        else:
            mask = torch.zeros((64,64), dtype=torch.float32, device="cpu")
        return (mask.unsqueeze(0),)
    
class SaveImage:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.type = "output"
        self.prefix_append = ""
        self.compress_level = 4

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "The images to save."}),
                "filename_prefix": ("STRING", {"default": "Output", "tooltip": "The prefix for the file to save. This may include formatting information such as %date:yyyy-MM-dd% or %Empty Latent Image.width% to include values from nodes."}),                
            },
            "optional": {
                "dpi_x": ("FLOAT", {"default": 0, "min": 0.0, "max": 1000.0, "step": 0.01, "tooltip": "The DPI of the image in the x direction."}),
                "dpi_y": ("FLOAT", {"default": 0, "min": 0.0, "max": 1000.0, "step": 0.01, "tooltip": "The DPI of the image in the y direction."}),
            },
            "hidden": {
                "prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO", "context": "TASK_CONTEXT"
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "save_images"

    OUTPUT_NODE = True

    CATEGORY = "comfygw"
    DESCRIPTION = "ComfyGW: Save Image"

    def save_images(self, images, filename_prefix="Output", dpi_x=0, dpi_y=0, prompt=None, extra_pnginfo=None, context=None):
        filename_prefix += self.prefix_append
        results = list()
        for (batch_number, image) in enumerate(images):
            # i = 255. * image.cpu().numpy()
            # 在 .numpy() 之前添加 .float() 将 BFloat16 转换为 Float32
            i = 255. * image.cpu().float().numpy()
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
            metadata = None
            
            dpi = None
            if dpi_x > 0 and dpi_y > 0:
                dpi = (dpi_x, dpi_y)

            file = upload_image(context, img, f"{filename_prefix}_{batch_number:05}", format="png", 
                                pnginfo=metadata, compress_level=self.compress_level, dpi=dpi)
            results.append({
                "name": f"{filename_prefix}_{batch_number:05}",
                "filename": file,
                "type": self.type,
                "size": { "width": img.width, "height": img.height },
                "mode": img.mode,
            })

        return { "ui": { "images": results } }
    
class PreviewImage(SaveImage):
    def __init__(self):
        self.type = "temp"
        self.prefix_append = "_preview"
        self.compress_level = 4
        
    @classmethod
    def INPUT_TYPES(s):
        return {"required":
                    {"images": ("IMAGE", ), },
                "hidden": 
                    {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO", "context": "TASK_CONTEXT"},
                }
    
class SaveText:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "name": ("STRING", {}),
                "text": ("STRING", {"multiline": True }),
            },            
        }

    INPUT_IS_LIST = True
    FUNCTION = "save_text"
    RETURN_TYPES = ()
    OUTPUT_NODE = True
    OUTPUT_IS_LIST = (True,)
    CATEGORY = "comfygw"
    DESCRIPTION = "ComfyGW: Save Text"

    def save_text(self, name, text):
        results = list()
        for n, t in zip(name, text):
            results.append(
                {
                    "name": n,
                    "text": t,
                }
            )
        return {"ui": {"text": results}}


class SaveSVG:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "svg_strings": ("STRING", {"forceInput": True}),
                "filename_prefix": ("STRING", {"default": "ComfyUI_SVG"}),
            },
            "hidden": {"context": "TASK_CONTEXT"},
        }

    CATEGORY = "comfygw"
    DESCRIPTION = "Comfygw: Save SVG data to a file."
    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save_svg_file"

    def save_svg_file(self, svg_strings, filename_prefix="ComfyUI_SVG", context=None):
        if isinstance(svg_strings, list):
            svgs_strings = svg_strings
        else:
            svgs_strings = [svg_strings]

        svgs = []
        for s in svgs_strings:
            bytes = s.encode("utf-8")
            filename = f"{filename_prefix}_{datetime.datetime.now()}.svg"
            file = upload_file(bytes, metadata=(
                ("access-token", env.taskq_access_key),
                ("file-name", filename),
                ("file-type", "image/svg+xml"),
                ("output-type", "workflow"),
                ("task-context", context.json())
            ))
            svgs.append({
                "name": filename,
                "filename": file,
            })

        return { "ui": { "svg": svgs, } }


class VideoUpload:
    @classmethod
    def INPUT_TYPES(s):
        return {"required":
                    {"video": ('STRING',)},
                }

    CATEGORY = "comfygw"
    DESCRIPTION = "ComfyGW: Load Video from Comfygw to local"

    RETURN_TYPES = ("STRING", "STRING",)
    RETURN_NAMES = ("video_filename", "video_path")
    FUNCTION = "load_video"

    def load_video(self, video):
        file_path = download_file(video)
        return (video, file_path,)

    @classmethod
    def IS_CHANGED(s, video):
        return get_file_hash(video)

    @classmethod
    def VALIDATE_INPUTS(s, video):
        return True
    

class AudioUpload:
    @classmethod
    def INPUT_TYPES(s):
        return {"required":
                    {"audio": ('STRING',)},
                }

    CATEGORY = "comfygw"
    DESCRIPTION = "ComfyGW: Load Audio from Comfygw to local."

    RETURN_TYPES = ("STRING", "STRING",)
    RETURN_NAMES = ("audio_filename", "audio_path",)
    FUNCTION = "load_audio"

    def load_audio(self, audio):
        file_path =download_file(audio)
        return (audio, file_path)
    
    @classmethod
    def IS_CHANGED(s, audio):
        return get_file_hash(audio)

    @classmethod
    def VALIDATE_INPUTS(s, audio):
        return True
    
class SaveVHSFiles:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "filenames": ("VHS_FILENAMES", ),
            },
            "hidden": {"context": "TASK_CONTEXT"},
        }

    CATEGORY = "comfygw"
    DESCRIPTION = "Comfygw: Save VHS files to a file."
    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save_vhs_files"

    def save_vhs_files(self, filenames, context=None):
        video_files = []
        image_files = []
        audio_files = []
        (_, output_files) = filenames

        # 预先缓存所有文件的 mime type
        file_types = {f: mimetypes.guess_type(f)[0] or "application/octet-stream" for f in output_files}

        # 只保留一个视频文件，优先保留包含 audio. 的
        video_candidates = [f for f, t in file_types.items() if t.startswith("video/")]
        selected_video = None
        if video_candidates:
            # 优先选择文件名包含 audio.
            for f in video_candidates:
                if "audio." in os.path.basename(f):
                    selected_video = f
                    break
            if not selected_video:
                selected_video = video_candidates[0]
            # 构建新的 output_files，只保留这个视频和其它非视频文件
            output_files = [
                f for f in output_files
                if f == selected_video or not file_types[f].startswith("video/")
            ]

        for file_path in output_files:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File {file_path} does not exist.")
            filename = os.path.basename(file_path)
            file_type = file_types[file_path]
            file = upload_file(
                file_path,
                metadata=(
                    ("access-token", env.taskq_access_key),
                    ("file-name", filename),
                    ("file-type", file_type),
                    ("output-type", "workflow"),
                    ("task-context", context.json()),
                )
            )
            file_info = {
                "name": filename,
                "filename": file,
            }
            if file_type.startswith("video/"):
                video_files.append(file_info)
            elif file_type.startswith("image/"):
                image_files.append(file_info)
            elif file_type.startswith("audio/"):
                audio_files.append(file_info)
            else:
                print(f"Unsupported file type for {filename}: {file_type}. Skipping.")

        return {
            "ui": {
                "audio": audio_files,
                "video": video_files,
                "images": image_files,
            }
        }

class LoadAudio(nodes_audio.LoadAudio):
    CATEGORY = "comfygw"
    DESCRIPTION = "ComfyGW: Load Audio from Comfygw to local."

    @classmethod
    def INPUT_TYPES(s):
        return {"required":
                    {"audio": ("STRING", )},
                }
    
    @classmethod
    def VALIDATE_INPUTS(s, audio):        
        return True

class LoadVideo(nodes_video.LoadVideo):
    CATEGORY = "comfygw"
    DESCRIPTION = "ComfyGW: Load Video from Comfygw to local."

    @classmethod
    def INPUT_TYPES(s):
        return {"required":
                    {"video": ("STRING",),},
                }
        
    @classmethod
    def VALIDATE_INPUTS(s, audio):        
        return True
    
def save_ui_output(ui_output, type, context=None):
    results = []
    for result in ui_output["ui"][type]:
        dir = folder_paths.get_directory_by_type(result["type"])
        file_path = os.path.join(
            dir, result["subfolder"], result["filename"]
        )
        file_ype = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        file_id = upload_file(
            file_path,
            metadata=(
                ("access-token", env.taskq_access_key),
                ("file-name", result["filename"]),
                ("file-type", file_ype),
                ("output-type", "workflow"),
                ("task-context", context.json())
            )
        )
        results.append({
            "name": result["filename"],
            "filename": file_id,
        })

    return {"ui": {type: results}}

class SaveAudio(nodes_audio.SaveAudio):
    CATEGORY = "comfygw"
    DESCRIPTION = "ComfyGW: Save Audio to Comfygw in flac format."

    @classmethod
    def INPUT_TYPES(s):
        super_input_types = super().INPUT_TYPES()
        super_input_types["hidden"]["context"] = "TASK_CONTEXT"
        return super_input_types

    def save_flac(self, audio, filename_prefix="ComfyUI", format="flac", prompt=None, extra_pnginfo=None, context=None):                
        ui_output = super().save_flac(audio, filename_prefix, format, prompt, extra_pnginfo)
        return save_ui_output(ui_output, "audio", context)
    
class SaveAudioMP3(nodes_audio.SaveAudioMP3):
    CATEGORY = "comfygw"
    DESCRIPTION = "ComfyGW: Save Audio to Comfygw in MP3 format."

    @classmethod
    def INPUT_TYPES(s):
        super_input_types = super().INPUT_TYPES()
        super_input_types["hidden"]["context"] = "TASK_CONTEXT"
        return super_input_types

    def save_mp3(self, audio, filename_prefix="ComfyUI", format="mp3", prompt=None, extra_pnginfo=None, quality="128k", context=None):
        ui_output = super().save_mp3(audio, filename_prefix, format, prompt, extra_pnginfo, quality)
        return save_ui_output(ui_output, "audio", context)

class SaveVideo(nodes_video.SaveVideo):
    CATEGORY = "comfygw"
    DESCRIPTION = "ComfyGW: Save Video to Comfygw."

    @classmethod
    def INPUT_TYPES(s):
        super_input_types = super().INPUT_TYPES()
        super_input_types["hidden"]["context"] = "TASK_CONTEXT"
        return super_input_types

    def save_video(self, video, filename_prefix, format, codec, prompt=None, extra_pnginfo=None, context=None):
        ui_output = super().save_video(video, filename_prefix, format, codec, prompt, extra_pnginfo)
        return save_ui_output(ui_output, "video", context)
    
    


EXTENSION_WEB_DIRS = nodes.EXTENSION_WEB_DIRS

def patch():
    nodes.NODE_CLASS_MAPPINGS["SaveImage"] = SaveImage
    nodes.NODE_CLASS_MAPPINGS["PreviewImage"] = PreviewImage
    nodes.NODE_CLASS_MAPPINGS["LoadImageMask"] = LoadImageMask
    nodes.NODE_CLASS_MAPPINGS["LoadImage"] = LoadImage
    nodes.NODE_CLASS_MAPPINGS["SaveText"] = SaveText
    nodes.NODE_CLASS_MAPPINGS["SaveSVG"] = SaveSVG
    nodes.NODE_CLASS_MAPPINGS["VideoUpload"] = VideoUpload
    nodes.NODE_CLASS_MAPPINGS["AudioUpload"] = AudioUpload
    nodes.NODE_CLASS_MAPPINGS["SaveVHSFiles"] = SaveVHSFiles
    nodes.NODE_CLASS_MAPPINGS["LoadAudio"] = LoadAudio
    nodes.NODE_CLASS_MAPPINGS["LoadVideo"] = LoadVideo
    nodes.NODE_CLASS_MAPPINGS["SaveAudio"] = SaveAudio
    nodes.NODE_CLASS_MAPPINGS["SaveAudioMP3"] = SaveAudioMP3
    nodes.NODE_CLASS_MAPPINGS["SaveVideo"] = SaveVideo

    nodes.NODE_DISPLAY_NAME_MAPPINGS["SaveText"] = "Save Text"
    nodes.NODE_DISPLAY_NAME_MAPPINGS["SaveSVG"] = "Save SVG"
    nodes.NODE_DISPLAY_NAME_MAPPINGS["VideoUpload"] = "Upload Video"
    nodes.NODE_DISPLAY_NAME_MAPPINGS["AudioUpload"] = "Upload Audio"
    nodes.NODE_DISPLAY_NAME_MAPPINGS["SaveVHSFiles"] = "Save VHS Files"
    nodes.NODE_DISPLAY_NAME_MAPPINGS["SaveAudio"] = "Save Audio (FLAC)"
    nodes.NODE_DISPLAY_NAME_MAPPINGS["SaveAudioMP3"] = "Save Audio (MP3)"
