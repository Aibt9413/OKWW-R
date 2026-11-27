import os.path

import cv2

from ok import Config, Logger, get_path_relative_to_exe, og

logger = Logger.get_logger(__name__)


class Globals:

    def __init__(self, exit_event):
        self._yolo_model = None
        self.mini_map_arrow = None
        self.logged_in = False

    @property
    def yolo_model(self):
        if self._yolo_model is None:
            model_dir = os.path.join("assets", "echo_model")
            sealed = get_path_relative_to_exe(os.path.join(model_dir, "audio_dsp_model.dat"))
            plain = get_path_relative_to_exe(os.path.join(model_dir, "echo.onnx"))

            weights = None
            if sealed and os.path.isfile(sealed):
                try:
                    from okunified.security.model_vault import load_model_bytes

                    weights = load_model_bytes(sealed)
                    logger.info(
                        f"yolo_model 从加密容器加载: {os.path.basename(sealed)} "
                        f"({len(weights)} bytes, 内存解密)")
                except Exception as e:
                    logger.error(f"解密模型失败，回退明文: {e}")

            if weights is None:
                weights = plain

            use_openvino = og.config.get("ocr").get("params").get("use_openvino")
            # 加密模型是 bytes，OpenVINO 那条路只接受路径，直接走 ORT
            if use_openvino and isinstance(weights, str):
                logger.info("yolo_model Using OpenVinoYolo8Detect")
                from src.OpenVinoYolo8Detect import OpenVinoYolo8Detect
                self._yolo_model = OpenVinoYolo8Detect(
                    weights=weights)
            else:
                logger.info("yolo_model Using OnnxYolo8Detect")
                from src.OnnxYolo8Detect import OnnxYolo8Detect
                self._yolo_model = OnnxYolo8Detect(
                    weights=weights)
        return self._yolo_model

    def yolo_detect(self, image, threshold=0.6, label=-1):
        return self.yolo_model.detect(image, threshold=threshold, label=label)


if __name__ == "__main__":
    glbs = Globals(exit_event=None)
