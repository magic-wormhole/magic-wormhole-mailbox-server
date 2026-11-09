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
      long_description=open('README.md').read(),
      long_description_content_type='text/markdown',
      author="Brian Warner",
      author_email="warner-magic-wormhole@lothar.com",
      license="MIT",
      url="https://github.com/warner/magic-wormhole-mailbox-server",
      classifiers=trove_classifiers,
      package_dir={"": "src"},
      packages=["wormhole_mailbox_server",
                "wormhole_mailbox_server.pubsub",
                "wormhole_mailbox_server.test",
                "twisted.plugins",
                ],
      package_data={"wormhole_mailbox_server": [
          "db-schemas/*.sql",
          "migrations/README",
          "migrations/versions/*.py",
      ]},
      install_requires=[
          "attrs >= 16.3.0", # 16.3.0 adds __attrs_post_init__
          "twisted[tls] >= 17.5.0",
          "autobahn[twisted] >= 0.14.1",
          "setuptools", # pkg_resources
          "SQLAlchemy >= 2.0",
          "alembic >= 1.13",
      ],
      extras_require={
          ':sys_platform=="win32"': ["pywin32"],
          "dev": ["treq", "tox", "pyflakes", "pymysql",
                  "psycopg[binary]", "redis", "confluent-kafka"],
          "postgres": ["psycopg[binary]"],
          "mysql": ["pymysql"],
          "redis": ["redis >= 4.0"],
          "kafka": ["confluent-kafka >= 2.0"],
          # Everything needed to run against any supported database or
          # pub/sub transport.  The Docker image installs this extra.
          "backends": ["psycopg[binary]", "pymysql",
                       "redis >= 4.0", "confluent-kafka >= 2.0"],
          "release": ["dulwich", "docutils", "wheel"],
      },
      test_suite="wormhole_mailbox_server.test",
      cmdclass=commands,
      )
