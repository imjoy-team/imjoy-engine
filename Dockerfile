FROM ubuntu:16.04

# System packages
RUN apt-get update && apt-get install -y curl bzip2

# Install miniconda to /miniconda
RUN curl -LO https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh
RUN bash Miniconda3-latest-Linux-x86_64.sh -p /miniconda -b
RUN rm Miniconda3-latest-Linux-x86_64.sh
ENV PATH=/miniconda/bin:${PATH}
RUN conda update -y conda

# Python packages from conda
RUN conda update conda && \
    conda update pip && \
    conda install -y python=3.6 numpy scipy git psutil && \
    pip install scikit-image Pillow && \
    pip install git+https://github.com/oeway/ImJoy-Engine#egg=imjoy
