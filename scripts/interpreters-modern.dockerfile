# The build environment for Python 2.6 through 3.14.
#
# Separate from `interpreters.dockerfile` on purpose, and not because the
# two could not share a base. The legacy image is part of the provenance
# of every answer the 0.9-to-2.5 half of the table already gives, and its
# id is recorded there. Adding a library to it to satisfy a 2011 release
# would change what compiled a 1991 one, which is the sort of quiet
# invalidation this pipeline exists to avoid. So the old image is left
# exactly as it is and this one is pinned alongside it.
#
# Same distribution as the legacy image, deliberately. The two halves of
# the table are diffed against each other, and "the library list changed
# half way along" is how an extraction method manufactures a release's
# worth of false additions. Ubuntu 22.04 is old enough that its gcc will
# compile Python 3.0 from 2008 and new enough to compile 3.14.
#
# The library list is what "importable in a default build on a modern
# Unix" means for this half, so it is pinned here rather than inherited
# from whatever the host had:
#
# - `libgdbm-compat-dev` carries `ndbm.h`, and installing `libgdbm-dev`
#   without it is worse than installing neither. The legacy image records
#   the same lesson.
# - `tk-dev` is here because `turtle` is a dataset entry and `turtle`
#   is `tkinter` with a pen. It needs no display to import.
# - `libnsl-dev` and `libtirpc-dev` are what `nis` wants after glibc
#   dropped it, and `uuid-dev` is what `_uuid` wants from 3.7 on.
#
# Deliberately absent, and the reason is worth writing down: nothing here
# supplies OpenSSL 1.1. Jammy ships OpenSSL 3, which the `_ssl` of every
# release before roughly 3.10 cannot compile against, so `ssl` reports as
# absent for most of this half of the corpus. That is exactly the case
# `absence_is_real` exists for: `Lib/ssl.py` is in all of those trees, so
# the absence is this build's and the oracle stays quiet rather than
# dating anything from it. Supplying a second OpenSSL and pointing each
# release at the one it likes would be per-release configuration, which
# is the line this file does not cross.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        zlib1g-dev \
        libbz2-dev \
        liblzma-dev \
        libssl-dev \
        libffi-dev \
        libexpat1-dev \
        libgdbm-dev \
        libgdbm-compat-dev \
        libncurses-dev \
        libreadline-dev \
        libsqlite3-dev \
        libnsl-dev \
        libtirpc-dev \
        uuid-dev \
        tk-dev \
    && rm -rf /var/lib/apt/lists/*
