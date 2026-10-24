FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d
COPY requirements.txt /tmp/requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk=1:20220127+repack1-1 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir --requirement /tmp/requirements.txt
RUN useradd --uid 65532 --no-create-home --shell /usr/sbin/nologin sandbox
USER 65532:65532
WORKDIR /work
ENV MPLCONFIGDIR=/tmp/matplotlib
