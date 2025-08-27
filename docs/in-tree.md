# Running in-tree
If you want to run the tools in tree, you need to make sure that distro dependencies
that would normally install into a venv are installed. This can be done by running:

    ./install_deps.py

After dependencies are installed, you can run the tools by running:

    ./amd_s2idle.py
    ./amd_bios.py
    ./amd_pstate.py
    ./amd_ttm.py
