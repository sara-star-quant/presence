FROM gcr.io/oss-fuzz-base/base-builder-python:v1
RUN pip3 install cryptography
COPY . $SRC/presence
WORKDIR $SRC/presence
COPY .clusterfuzzlite/build.sh $SRC/
