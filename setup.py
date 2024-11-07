from setuptools import setup

import versioneer

commands = versioneer.get_cmdclass()

trove_classifiers = [
    "Development Status :: 4 - Beta",
    "Environment :: Console",
    "License :: OSI Approved :: MIT License",
    "Topic :: Security :: Cryptography",
    "Topic :: System :: Networking",
    "Topic :: System :: Systems Administration",
    "Topic :: Utilities",
    ]

setup(name="magic-wormhole-mailbox-server",
      version=versioneer.get_version(),
      description="Securely transfer data between computers",
      long_description=open('README.md', 'r').read(),
      long_description_content_type='text/markdown',
      author="Brian Warner",
      author_email="warner-magic-wormhole@lothar.com",
      license="MIT",
      url="https://github.com/warner/magic-wormhole-mailbox-server",
      classifiers=trove_classifiers,
      package_dir={"": "src"},
      packages=["wormhole_mailbox_server",
                "wormhole_mailbox_server.test",
                "twisted.plugins",
                ],
      package_data={"wormhole_mailbox_server": ["db-schemas/*.sql"]},
      install_requires=[
          "attrs >= 16.3.0", # 16.3.0 adds __attrs_post_init__
          "twisted[tls] >= 17.5.0",
          "autobahn[twisted] >= 0.14.1",
      ],
      extras_require={
          ':sys_platform=="win32"': ["pywin32"],
          "dev": ["mock", "treq", "tox", "pyflakes"],
          "release": ["dulwich", "docutils", "gpg", "wheel"],
      },
      test_suite="wormhole_mailbox_server.test",
      cmdclass=commands,
      )
