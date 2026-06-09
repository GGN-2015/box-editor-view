from __future__ import annotations

from dataclasses import dataclass


SOFTWARE_RENDERER_KEYWORDS = ("software", "llvmpipe", "mesa x11", "gdi generic", "swiftshader")
DISCRETE_GPU_KEYWORDS = ("nvidia", "geforce", "rtx", "gtx", "radeon", "rx ", "arc")


@dataclass(frozen=True)
class GpuProfile:
    vendor: str = "Unknown"
    renderer: str = "Unknown"
    version: str = "Unknown"
    hardware_accelerated: bool = False
    discrete_gpu: bool = False
    supports_basic_shaders: bool = False
    supports_depth_texture: bool = False
    supports_multisample: bool = False
    shadow_map_size: int = 0
    antialias_enabled: bool = False
    shader_auto_enabled: bool = False

    @property
    def label(self) -> str:
        return f"{self.vendor} {self.renderer}".strip()


def detect_gpu_profile(gsg: object | None) -> GpuProfile:
    if gsg is None:
        return GpuProfile()

    vendor = _call_string(gsg, "getDriverVendor")
    renderer = _call_string(gsg, "getDriverRenderer")
    version = _call_string(gsg, "getDriverVersion")
    supports_basic_shaders = _call_bool(gsg, "getSupportsBasicShaders")
    supports_depth_texture = _call_bool(gsg, "getSupportsDepthTexture")
    supports_multisample = _call_bool(gsg, "getSupportsMultisample")

    hardware_accelerated = _looks_hardware_accelerated(vendor, renderer)
    discrete_gpu = _looks_discrete_gpu(vendor, renderer)
    shadow_map_size = _shadow_map_size(hardware_accelerated, discrete_gpu, supports_depth_texture)

    return GpuProfile(
        vendor=vendor,
        renderer=renderer,
        version=version,
        hardware_accelerated=hardware_accelerated,
        discrete_gpu=discrete_gpu,
        supports_basic_shaders=supports_basic_shaders,
        supports_depth_texture=supports_depth_texture,
        supports_multisample=supports_multisample,
        shadow_map_size=shadow_map_size,
        antialias_enabled=hardware_accelerated and supports_multisample,
        shader_auto_enabled=hardware_accelerated and supports_basic_shaders,
    )


def _call_string(source: object, method_name: str) -> str:
    method = getattr(source, method_name, None)
    if method is None:
        return "Unknown"
    try:
        value = str(method()).strip()
    except Exception:
        return "Unknown"
    return value or "Unknown"


def _call_bool(source: object, method_name: str) -> bool:
    method = getattr(source, method_name, None)
    if method is None:
        return False
    try:
        return bool(method())
    except Exception:
        return False


def _looks_hardware_accelerated(vendor: str, renderer: str) -> bool:
    text = f"{vendor} {renderer}".lower()
    if any(keyword in text for keyword in SOFTWARE_RENDERER_KEYWORDS):
        return False
    return vendor != "Unknown" or renderer != "Unknown"


def _looks_discrete_gpu(vendor: str, renderer: str) -> bool:
    text = f"{vendor} {renderer}".lower()
    return any(keyword in text for keyword in DISCRETE_GPU_KEYWORDS)


def _shadow_map_size(hardware_accelerated: bool, discrete_gpu: bool, supports_depth_texture: bool) -> int:
    if not hardware_accelerated or not supports_depth_texture:
        return 0
    if discrete_gpu:
        return 2048
    return 1024
