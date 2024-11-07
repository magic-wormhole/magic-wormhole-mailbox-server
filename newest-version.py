#
# print out the most-recent version
#

from dulwich.repo import Repo
from dulwich.porcelain import tag_list


def existing_tags(git):
    versions = [
        tuple(map(int, v.decode("utf8").split(".")))
        for v in tag_list(git)
    ]
    return versions


def main():
    git = Repo(".")
    print("{}.{}.{}".format(*sorted(existing_tags(git))[-1]))


if __name__ == "__main__":
    main()
