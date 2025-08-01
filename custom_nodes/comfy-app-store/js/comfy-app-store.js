import { app } from '../../scripts/app.js'
import { api } from '../../scripts/api.js';

function createElement(tag, attrs = {}, children = []) {
  const el = document.createElement(tag);
  Object.assign(el, attrs);
  children.forEach(child => el.appendChild(typeof child === 'string' ? document.createTextNode(child) : child));
  return el;
}

let ticket = new URLSearchParams(window.location.search).get('ticket')

const clearCache = () => {
  // 清理 sessionStorage
  let sessionKeys = [];
  for (let i = 0; i < sessionStorage.length; i++) {
    let k = sessionStorage.key(i);
    if (k && (k.startsWith('Comfy') || k.startsWith('workflow:'))) {
      sessionKeys.push(k);
    }
  }
  sessionKeys.forEach(k => sessionStorage.removeItem(k));

  // 清理 localStorage
  let localKeys = [];
  for (let i = 0; i < localStorage.length; i++) {
    let k = localStorage.key(i);
    if (k && (k.startsWith('Comfy') || k.startsWith('workflow'))) {
      localKeys.push(k);
    }
  }
  localKeys.forEach(k => localStorage.removeItem(k));
}

const createUploaderWidget = (node, type) => {
  // Find the regular STRING widget that will hold the ComfyUI filename
  const filenameWidget = node.widgets.find((w) => w.name === type);
  if (!filenameWidget) {
    console.error(`RH_Uploader: Could not find '${type}' widget on node:`, node.id);
    return;
  }

  // --- Create Custom UI Elements (Button, Preview, Status) ---
  const container = document.createElement("div");
  container.style.margin = "5px 0";

  const uploadButton = createElement("button", {
    textContent: `Select ${type.charAt(0).toUpperCase() + type.slice(1)}`,
    style: "width: 100%; margin-bottom: 5px;"
  });

  const previewArea = createElement("div", {
    style: "width: 100%; max-width: 256px; aspect-ratio: 16/9; background: #333; border-radius: 4px; margin-bottom: 5px; overflow: hidden; display: none; position: relative; margin-left: auto; margin-right: auto;"
  });

  // 动态创建 video 或 audio 预览
  const previewMedia = createElement(type, {
    controls: true,
    style: "width: 100%; height: 100%; display: block;"
  });

  const statusText = createElement("p", {
    textContent: `No ${type} selected.`,
    style: "margin: 0; padding: 2px 5px; font-size: 0.8em; color: #ccc; text-align: center;"
  });

  previewArea.appendChild(previewMedia);
  container.appendChild(uploadButton);
  container.appendChild(previewArea);
  container.appendChild(statusText);

  node.addDOMWidget(`${type}_uploader_widget`, "preview", container);

  // Function to upload file to ComfyUI backend
  async function uploadFileToComfyUI(file) {
    statusText.textContent = `Uploading ${file.name} to ComfyUI...`;
    uploadButton.disabled = true;
    uploadButton.textContent = "Uploading...";
    filenameWidget.value = "";

    try {
      const body = new FormData();
      // 依然用 image 字段，后端已支持 video/audio
      body.append('image', file);

      const resp = await api.fetchApi("/upload/image", {
        method: "POST",
        body,
      });

      if (resp.status === 200 || resp.status === 201) {
        const data = await resp.json();
        if (data.name) {
          const comfyFilename = data.subfolder ? `${data.subfolder}/${data.name}` : data.name;
          filenameWidget.value = comfyFilename;
          statusText.textContent = `${type.charAt(0).toUpperCase() + type.slice(1)} ready: ${comfyFilename}`;
          uploadButton.textContent = `${type.charAt(0).toUpperCase() + type.slice(1)} Selected`;
        } else {
          throw new Error("Filename not found in ComfyUI upload response.");
        }
      } else {
        throw new Error(`ComfyUI upload failed: ${resp.status} ${resp.statusText}`);
      }
    } catch (error) {
      console.error(`Upload: ComfyUI upload error:`, error);
      statusText.textContent = `Error uploading to ComfyUI: ${error.message}`;
      filenameWidget.value = "ERROR";
    } finally {
      uploadButton.disabled = false;
      if (filenameWidget.value && filenameWidget.value !== "ERROR") {
        uploadButton.textContent = `Select Another ${type.charAt(0).toUpperCase() + type.slice(1)}`;
      } else {
        uploadButton.textContent = `Select ${type.charAt(0).toUpperCase() + type.slice(1)}`;
      }
    }
  }

  // --- Event Listener for Button --- 
  uploadButton.addEventListener("click", () => {
    const acceptMap = {
      video: "video/mp4,video/webm,video/ogg,video/quicktime,video/x-matroska,video/*",
      audio: "audio/mpeg,audio/wav,audio/ogg,audio/mp3,audio/*"
    };
    const fileInput = createElement("input", {
      type: "file",
      accept: acceptMap[type] || "",
      style: "display: none;"
    });

    fileInput.addEventListener("change", (event) => {
      const file = event.target.files[0];
      if (file) {
        // Show preview
        try {
          const objectURL = URL.createObjectURL(file);
          previewMedia.src = objectURL;
          if (previewMedia.dataset.objectUrl) {
            URL.revokeObjectURL(previewMedia.dataset.objectUrl);
          }
          previewMedia.dataset.objectUrl = objectURL;
          previewArea.style.display = "block";
        } catch (e) {
          console.error("Error creating object URL for preview:", e);
          previewArea.style.display = "none";
          statusText.textContent = "Preview failed. Ready to upload.";
        }

        uploadFileToComfyUI(file);
      }
      fileInput.remove();
    });

    document.body.appendChild(fileInput);
    fileInput.click();
  });

  // Clean up object URL when node is removed
  const onRemoved = node.onRemoved;
  node.onRemoved = () => {
    if (previewMedia.dataset.objectUrl) {
      URL.revokeObjectURL(previewMedia.dataset.objectUrl);
    }
    onRemoved?.();
  };
};


/**
 * 轮询等待 window['app'] 和 window['graph'] 加载完成
 * @returns {Promise<void>}
 */
function waitForAppAndGraphReady(interval = 100, timeout = 100000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    function check() {
      if (window['app'] && window['graph']) {
        resolve();
      } else if (Date.now() - start > timeout) {
        reject(new Error('Timeout: app or graph not ready'));
      } else {
        setTimeout(check, interval);
      }
    }
    check();
  });
}

const isMediaUploadComboInput = (inputSpec) => {
  const [inputName, inputOptions] = inputSpec
  if (!inputOptions) return false

  const isUploadInput =
    inputOptions['image_upload'] === true ||
    inputOptions['video_upload'] === true ||
    inputOptions['animated_image_upload'] === true

  return isUploadInput
}

const createUploadInput = (
  imageInputName,
  imageInputOptions
) => [
  'IMAGEUPLOAD',
  {
    ...imageInputOptions[1],
    imageInputName
  }
]


app.registerExtension({
  name: 'Comfy.AppStore',

  beforeRegisterNodeDef(_nodeType, nodeData) {
    const { input } = nodeData ?? {}
    const { required } = input ?? {}
    if (!required) return

    const found = Object.entries(required).find(([_, input]) =>
      isMediaUploadComboInput(input)
    )

    if (found) {
      const [inputName, inputSpec] = found
      required.upload = createUploadInput(inputName, inputSpec)
    }
  },

  nodeCreated: (node) => {
    if (node.comfyClass == 'VideoUpload') {
      createUploaderWidget(node, 'video');
    } else if (node.comfyClass == 'AudioUpload') {
      createUploaderWidget(node, 'audio');
    }
  },

  setup: async () => {
    try {
      let cmGroup = new (await import("../../scripts/ui/components/buttonGroup.js")).ComfyButtonGroup(
        new (await import("../../scripts/ui/components/button.js")).ComfyButton({
          icon: "file",
          action: () => {
            app.graphToPrompt().then(async (p) => {
              //console.log(p);
              const json = JSON.stringify({
                workflow: p.workflow,
                prompt: p.output
              }) // convert the data to a JSON string  
              sessionStorage.setItem(`comfy-editor-output-${ticket}`, json)
            })
          },
          tooltip: "Save App",
          content: "保存APP",
          classList: "comfyui-button comfyui-menu-mobile-collapse primary"
        }).element
      );

      app.menu?.settingsGroup.element.before(cmGroup.element);
    }
    catch (exception) {
      console.log('ComfyUI is outdated. New style menu based features are disabled.');
    }

    let workflowJSON = null;
    if (ticket) {
      workflowJSON = sessionStorage.getItem(
        `comfy-editor-input-${ticket}`
      )
    }

    clearCache();

    (async () => {
      // 等待 app 和 graph 加载完
      await waitForAppAndGraphReady();
      app.graph.clear();
      if (workflowJSON) {
        try {
          let { name: workflowName, workflow, id } = JSON.parse(workflowJSON)
          if (workflow) {
            await app.loadGraphData(workflow, true, true, workflowName)
          }
        } catch (e) {
          console.error("Failed to load workflow from session storage:", e);
        }
      }
    })();
  },
});