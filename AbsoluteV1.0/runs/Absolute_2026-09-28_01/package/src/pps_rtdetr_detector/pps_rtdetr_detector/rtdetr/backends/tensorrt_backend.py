"""TensorRT backend for an RT-DETRv2 deploy engine (``.engine`` / ``.plan``).

Loads a serialized engine exported via the official ``export_onnx.py`` +
``trtexec`` path (inputs ``images`` + ``orig_target_sizes``; outputs ``labels``,
``boxes``, ``scores``). I/O is bound **by tensor name**, not by index, and both
the TensorRT 10 (``execute_async_v3``) and the TensorRT 8 (``execute_v2``) APIs
are supported. ``tensorrt`` and ``pycuda`` are imported lazily so the rest of
the package (and the mock backend / tests) never require a CUDA stack.

Assumptions: single image per call (batch = 1), engine input ``640 x 640``
(configurable). Drop your engine somewhere on disk and point ``engine_path`` at
it -- no code changes required.
"""

from __future__ import annotations

import numpy as np

from .base import DetectorBackend


class TensorRTBackend(DetectorBackend):
    def __init__(
        self,
        engine_path: str,
        *,
        input_size: int = 640,
        images_input_name: str = "images",
        sizes_input_name: str = "orig_target_sizes",
        output_names: tuple[str, str, str] = ("labels", "boxes", "scores"),
        log_severity: str = "WARNING",
    ):
        try:
            import tensorrt as trt  # noqa: F401
            import pycuda.autoinit  # noqa: F401  (creates a CUDA context)
            import pycuda.driver as cuda
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "TensorRTBackend requires 'tensorrt' and 'pycuda'. Install them in the "
                "deployment environment, or use backend='mock' for testing."
            ) from exc

        self._trt = trt
        self._cuda = cuda
        self._input_size = int(input_size)
        self._images_input_name = images_input_name
        self._sizes_input_name = sizes_input_name
        self._output_names = tuple(output_names)

        logger = trt.Logger(getattr(trt.Logger, log_severity, trt.Logger.WARNING))
        with open(engine_path, "rb") as handle, trt.Runtime(logger) as runtime:
            self._engine = runtime.deserialize_cuda_engine(handle.read())
        if self._engine is None:
            raise RuntimeError(f"failed to deserialize TensorRT engine: {engine_path}")
        self._context = self._engine.create_execution_context()
        self._stream = cuda.Stream()
        self._uses_v3 = hasattr(self._engine, "num_io_tensors")

        self._buffers: dict[str, dict] = {}
        self._allocate()

    # -- public API ------------------------------------------------------
    @property
    def input_hw(self) -> tuple[int, int]:
        return (self._input_size, self._input_size)

    def infer(self, images: np.ndarray, orig_target_sizes: np.ndarray) -> dict[str, np.ndarray]:
        cuda = self._cuda
        self._set_input(self._images_input_name, images.astype(np.float32))
        self._set_input(self._sizes_input_name, orig_target_sizes.astype(np.int64))

        for name, buf in self._buffers.items():
            if buf["is_input"]:
                cuda.memcpy_htod_async(buf["device"], buf["host"], self._stream)

        self._execute()

        outputs: dict[str, np.ndarray] = {}
        for name, buf in self._buffers.items():
            if not buf["is_input"]:
                cuda.memcpy_dtoh_async(buf["host"], buf["device"], self._stream)
        self._stream.synchronize()

        for key in self._output_names:
            if key not in self._buffers:
                raise KeyError(
                    f"engine has no output tensor named '{key}'. Available: "
                    f"{sorted(self._buffers)}"
                )
            buf = self._buffers[key]
            outputs[key] = buf["host"].reshape(buf["shape"]).copy()
        return outputs

    def close(self) -> None:  # pragma: no cover - GPU teardown
        self._buffers.clear()

    # -- internals -------------------------------------------------------
    def _tensor_names(self) -> list[str]:
        if self._uses_v3:
            return [self._engine.get_tensor_name(i) for i in range(self._engine.num_io_tensors)]
        return [self._engine.get_binding_name(i) for i in range(self._engine.num_bindings)]

    def _is_input(self, name: str) -> bool:
        trt = self._trt
        if self._uses_v3:
            return self._engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT
        return self._engine.binding_is_input(self._engine.get_binding_index(name))

    def _dtype(self, name: str):
        trt = self._trt
        if self._uses_v3:
            return trt.nptype(self._engine.get_tensor_dtype(name))
        return trt.nptype(self._engine.get_binding_dtype(self._engine.get_binding_index(name)))

    def _set_shape(self, name: str, shape: tuple[int, ...]) -> None:
        if self._uses_v3:
            self._context.set_input_shape(name, shape)
        else:
            self._context.set_binding_shape(self._engine.get_binding_index(name), shape)

    def _current_shape(self, name: str) -> tuple[int, ...]:
        if self._uses_v3:
            return tuple(self._context.get_tensor_shape(name))
        return tuple(self._context.get_binding_shape(self._engine.get_binding_index(name)))

    def _allocate(self) -> None:
        cuda = self._cuda
        # Fix batch = 1 input shapes so output shapes resolve.
        self._set_shape(self._images_input_name, (1, 3, self._input_size, self._input_size))
        self._set_shape(self._sizes_input_name, (1, 2))

        for name in self._tensor_names():
            shape = self._current_shape(name)
            dtype = np.dtype(self._dtype(name))
            host = cuda.pagelocked_empty(int(np.prod(shape)), dtype)
            device = cuda.mem_alloc(host.nbytes)
            self._buffers[name] = {
                "host": host,
                "device": device,
                "shape": shape,
                "dtype": dtype,
                "is_input": self._is_input(name),
            }
            if self._uses_v3:
                self._context.set_tensor_address(name, int(device))

    def _set_input(self, name: str, array: np.ndarray) -> None:
        buf = self._buffers[name]
        np.copyto(buf["host"], np.ascontiguousarray(array, dtype=buf["dtype"]).reshape(-1))

    def _execute(self) -> None:
        if self._uses_v3:
            self._context.execute_async_v3(stream_handle=self._stream.handle)
        else:
            bindings = [0] * self._engine.num_bindings
            for name, buf in self._buffers.items():
                bindings[self._engine.get_binding_index(name)] = int(buf["device"])
            self._context.execute_async_v2(bindings, self._stream.handle)
