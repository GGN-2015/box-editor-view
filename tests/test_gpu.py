from box_editor_view.gpu import detect_gpu_profile


class FakeGsg:
    def __init__(
        self,
        vendor="Unknown",
        renderer="Unknown",
        version="Unknown",
        basic_shaders=False,
        depth_texture=False,
        multisample=False,
    ):
        self.vendor = vendor
        self.renderer = renderer
        self.version = version
        self.basic_shaders = basic_shaders
        self.depth_texture = depth_texture
        self.multisample = multisample

    def getDriverVendor(self):
        return self.vendor

    def getDriverRenderer(self):
        return self.renderer

    def getDriverVersion(self):
        return self.version

    def getSupportsBasicShaders(self):
        return self.basic_shaders

    def getSupportsDepthTexture(self):
        return self.depth_texture

    def getSupportsMultisample(self):
        return self.multisample


def test_detect_gpu_profile_enables_discrete_gpu_settings():
    profile = detect_gpu_profile(
        FakeGsg(
            vendor="NVIDIA Corporation",
            renderer="NVIDIA GeForce RTX 5060 Laptop GPU",
            version="4.6",
            basic_shaders=True,
            depth_texture=True,
            multisample=True,
        )
    )

    assert profile.hardware_accelerated
    assert profile.discrete_gpu
    assert profile.shadow_map_size == 2048
    assert profile.shader_auto_enabled
    assert profile.antialias_enabled


def test_detect_gpu_profile_uses_conservative_integrated_gpu_settings():
    profile = detect_gpu_profile(
        FakeGsg(
            vendor="Intel",
            renderer="Intel UHD Graphics",
            basic_shaders=True,
            depth_texture=True,
            multisample=False,
        )
    )

    assert profile.hardware_accelerated
    assert not profile.discrete_gpu
    assert profile.shadow_map_size == 1024
    assert profile.shader_auto_enabled
    assert not profile.antialias_enabled


def test_detect_gpu_profile_disables_expensive_features_for_software_renderers():
    profile = detect_gpu_profile(
        FakeGsg(
            vendor="Mesa",
            renderer="llvmpipe software renderer",
            basic_shaders=True,
            depth_texture=True,
            multisample=True,
        )
    )

    assert not profile.hardware_accelerated
    assert profile.shadow_map_size == 0
    assert not profile.shader_auto_enabled
    assert not profile.antialias_enabled


def test_detect_gpu_profile_handles_missing_gsg():
    profile = detect_gpu_profile(None)

    assert not profile.hardware_accelerated
    assert profile.vendor == "Unknown"
    assert profile.shadow_map_size == 0
