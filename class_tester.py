import podmaner


podman_container = podmaner.Podmaner('sample_conf', './')
podman_container.read_config_file()
podman_container.start_container()
