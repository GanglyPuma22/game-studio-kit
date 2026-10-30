#!/bin/bash
# Runtime side (Colab VM, root): a virtual screen with Vulkan on the runtime's
# NVIDIA GPU, for engines that need a window to render. Writes $JOB/display.env
# (DISPLAY, VK_ICD_FILENAMES) and $JOB/env.txt (what was found).
#
# Learned on Salvage's Colab runs (Oct 2026, L4, driver 580): Xvfb :99 started
# with Mesa GLX and -noreset works; Vulkan then reaches the L4 through the
# host's NVIDIA ICD (/usr/lib64-nvidia). Presenting to that screen fails
# (VkResult -13), which stalls each frame: frames render correctly, so clips
# and stills are fine, but frame timings are not to be trusted. A job that
# needs GPU timings has to skip presenting (Salvage built an engine for that).
# When no NVIDIA ICD works, the software driver (lavapipe) is used and env.txt
# says gpu=software, so nobody mistakes the result for a GPU run.
set -u
JOB=${JOB_ROOT:-/content/job}
ENV=$JOB/env.txt
if [ "${1:-}" = --no-screen ]; then
	# Model runs and headless jobs (CPU runtimes): no screen; just record the
	# CPU, memory and GPU, if any.
	{ nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>/dev/null || echo "no nvidia-smi"
	  echo "nproc $(nproc)"; lscpu 2>/dev/null | grep -E "Model name" | head -1; free -g | sed -n 2p
	  if nvidia-smi > /dev/null 2>&1; then echo "gpu=nvidia (no screen)"; else echo "gpu=none (CPU runtime or no NVIDIA driver answered)"; fi
	} > "$ENV"
	cat "$ENV"; exit 0
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq > /dev/null
apt-get install -y -qq xvfb xauth x11-utils vulkan-tools libvulkan1 mesa-vulkan-drivers libgl1-mesa-dri \
	libglx-mesa0 libegl-mesa0 libxcursor1 libxinerama1 libxrandr2 libxi6 libgl1 ffmpeg unzip > /dev/null
{
	nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>/dev/null || echo "no nvidia-smi"
	echo "nproc $(nproc)"; lscpu | grep -E "Model name" | head -1; free -g | sed -n 2p
} > "$ENV"
mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix
if ! xdpyinfo -display :99 > /dev/null 2>&1; then
	setsid env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root \
		__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json __GLX_VENDOR_LIBRARY_NAME=mesa \
		Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp -noreset +extension GLX < /dev/null > "$JOB/xvfb.log" 2>&1 &
	for _ in $(seq 40); do xdpyinfo -display :99 > /dev/null 2>&1 && break; sleep 0.5; done
fi
xdpyinfo -display :99 > /dev/null 2>&1 || { echo "screen: Xvfb :99 did not start" >> "$ENV"; exit 1; }
mkdir -p "$JOB/icd"
CHOSEN=""
for lib in /usr/lib64-nvidia/libGLX_nvidia.so.0 /usr/lib/x86_64-linux-gnu/libGLX_nvidia.so.0; do
	[ -e "$lib" ] || continue
	echo "{\"file_format_version\":\"1.0.0\",\"ICD\":{\"library_path\":\"$lib\",\"api_version\":\"1.3.0\"}}" > "$JOB/icd/nvidia.json"
	if DISPLAY=:99 VK_ICD_FILENAMES=$JOB/icd/nvidia.json LD_LIBRARY_PATH="$(dirname "$lib"):${LD_LIBRARY_PATH:-}" \
		vulkaninfo --summary 2> /dev/null | grep -q "NVIDIA"; then
		CHOSEN=$lib; break
	fi
done
if [ -n "$CHOSEN" ]; then
	printf 'export DISPLAY=:99\nexport VK_ICD_FILENAMES=%s\nexport VK_DRIVER_FILES=%s\nexport LD_LIBRARY_PATH="%s:${LD_LIBRARY_PATH:-}"\n' \
		"$JOB/icd/nvidia.json" "$JOB/icd/nvidia.json" "$(dirname "$CHOSEN")" > "$JOB/display.env"
	echo "gpu=nvidia icd=$CHOSEN screen=:99" >> "$ENV"
else
	printf 'export DISPLAY=:99\n' > "$JOB/display.env"
	echo "gpu=software (no NVIDIA Vulkan driver answered; lavapipe will draw)" >> "$ENV"
fi
cat "$ENV"
