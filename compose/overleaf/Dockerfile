# Frozen upstream application and historic TeX repository. No startup downloads.
FROM sharelatex/sharelatex:6.1.0@sha256:779d05d794b54cdb5e1b26f91fdd3b8b733b0c9461f8d75ae3d9ca02a588df27
RUN test -d /usr/local/texlive/2025 \
    && tlmgr option repository https://ftp.math.utah.edu/pub/tex/historic/systems/texlive/2025/tlnet-final \
    && tlmgr update --self \
    && tlmgr install scheme-full \
    && luaotfload-tool --update --force \
    && lualatex --version \
    && test -n "$(kpsewhich fontspec.sty)" \
    && test -n "$(kpsewhich tabularray.sty)"
