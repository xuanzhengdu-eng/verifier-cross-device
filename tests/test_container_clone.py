import unittest

from deploy.container_clone import build_run_args


class ContainerCloneTests(unittest.TestCase):
    def test_build_args_isolates_data_and_publishes_port(self):
        inspected = {
            "Name": "/gosim_server",
            "HostConfig": {
                "NetworkMode": "default",
                "Privileged": True,
                "IpcMode": "host",
                "PidMode": "",
                "ShmSize": 1024,
                "Devices": [
                    {
                        "PathOnHost": "/dev/card0",
                        "PathInContainer": "/dev/card0",
                        "CgroupPermissions": "rwm",
                    }
                ],
            },
            "Mounts": [
                {"Source": "/data", "Destination": "/data", "Mode": "rw"},
                {"Source": "/driver", "Destination": "/usr/local/driver", "Mode": "rw"},
            ],
        }
        args = build_run_args(inspected, "vcd-work", "vcd:snapshot", 9100, 9100)
        self.assertIn("9100:9100", args)
        self.assertIn("/dev/card0:/dev/card0:rwm", args)
        self.assertNotIn("/data:/data:rw", args)
        self.assertIn("/driver:/usr/local/driver:ro", args)
        self.assertIn("vcd.base-container=gosim_server", args)


if __name__ == "__main__":
    unittest.main()

