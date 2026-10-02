from pathlib import Path

Import("env")

framework_dir = Path(env.PioPlatform().get_package_dir("framework-stm32cubef1"))
freertos_dir = framework_dir / "Middlewares" / "Third_Party" / "FreeRTOS" / "Source"

env.Append(
    CPPPATH=[
        str(freertos_dir / "include"),
        str(freertos_dir / "portable" / "GCC" / "ARM_CM3"),
    ]
)

env.BuildSources(
    "$BUILD_DIR/FreeRTOS",
    str(freertos_dir),
    src_filter=[
        "+<*.c>",
        "+<portable/GCC/ARM_CM3/*.c>",
        "+<portable/MemMang/heap_4.c>",
    ],
)