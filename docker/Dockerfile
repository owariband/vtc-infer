ARG VLLM_BASE_IMAGE=vllm/vllm-openai@sha256:c2914767605584b6d8f45686b82de173ecc99e781897aa3d0a66dacd72c51ae1
FROM ${VLLM_BASE_IMAGE}

ARG VTC_INFER_VERSION=0.2.0
ARG VTC_INFER_GIT_SHA=unknown

LABEL org.opencontainers.image.title="VTC-Infer vLLM"
LABEL org.opencontainers.image.version="${VTC_INFER_VERSION}"
LABEL org.opencontainers.image.revision="${VTC_INFER_GIT_SHA}"
LABEL org.opencontainers.image.source="https://github.com/owariband/vtc-infer"

WORKDIR /opt/vtc-infer-src
COPY pyproject.toml README.md ./
COPY tinyinfer ./tinyinfer
COPY patches/vllm-v0.29.0-custom-async-scheduler-warning.patch /tmp/vllm-async-warning.patch

RUN python3 -m pip install --no-cache-dir --no-deps . \
    && apt-get update \
    && apt-get install -y --no-install-recommends patch \
    && VLLM_SITE="$(python3 -c 'from pathlib import Path; import vllm; print(Path(vllm.__file__).resolve().parent.parent)')" \
    && patch --directory "${VLLM_SITE}" --strip=1 < /tmp/vllm-async-warning.patch \
    && apt-get purge -y --auto-remove patch \
    && rm -rf /var/lib/apt/lists/* /tmp/vllm-async-warning.patch /opt/vtc-infer-src

RUN mkdir -p /opt/vtc-infer \
    && printf '{"version":"%s","git_sha":"%s","vllm":"0.29.0"}\n' \
      "${VTC_INFER_VERSION}" "${VTC_INFER_GIT_SHA}" \
      > /opt/vtc-infer/build-info.json \
    && command -v vllm \
    && python3 -c 'from tinyinfer.scheduler.vllm_adapter import CustomAsyncFCFSScheduler, VTCScheduler'

ENV VTC_INFER_VERSION=${VTC_INFER_VERSION}
ENV VTC_INFER_GIT_SHA=${VTC_INFER_GIT_SHA}

WORKDIR /root
