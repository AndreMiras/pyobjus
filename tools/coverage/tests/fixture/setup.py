from Cython.Distutils import Extension, build_ext
from setuptools import setup


setup(
    name="pxi-coverage-fixture",
    version="0.0.0",
    packages=["pxiprobe"],
    cmdclass={"build_ext": build_ext},
    ext_modules=[
        Extension(
            f"pxiprobe.{name}", [f"pxiprobe/{name}.pyx"],
            cython_directives={"linetrace": True, "emit_code_comments": True},
            define_macros=[("CYTHON_TRACE", "1"), ("CYTHON_USE_SYS_MONITORING", "0")],
        )
        for name in ("bridge", "cold")
    ],
)
