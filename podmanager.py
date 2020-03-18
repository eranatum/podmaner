import podmaner
import argparse


parser = argparse.ArgumentParser()

parser.add_argument("command",
                    help="Type of command that you want to execute on desired\
                           container")
parser.add_argument("container_name", help="Container name on which\
                     you want run command")
args = parser.parse_args()

if args.command in ['start', 'stop']:
    print("Executing [" + args.command + "] of [" + args.container_name + "] container")
    podman_container = podmaner.Podmaner(args.container_name)
    podman_container.read_config_file()
    if args.command == 'start':
        podman_container.start_container()
    else:
        podman_container.stop_container()
else:
    print("Command not known :/")
