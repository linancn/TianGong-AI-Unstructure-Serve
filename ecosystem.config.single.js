// ecosystem.config.js
module.exports = {
  apps: [
    {
      name: "unstructured-uvicorn-0",
      cwd: __dirname,
      script: ".venv/bin/uvicorn",
      interpreter: "none",
      args: "src.main:app --host 0.0.0.0 --port 7770",
      env: {
        CUDA_VISIBLE_DEVICES: "2",
        MINERU_MODEL_SOURCE: "modelscope",
        TABLE_OCR: "paddle",
        OCR_AGENT: "unstructured.partition.utils.ocr_models.paddle_ocr.OCRAgentPaddle",
        VISION_PROVIDER: "gemini"
      },
      out_file: "uvicorn-0.log",
      error_file: "uvicorn-0.log",
      time: true
    },
  ]
}
