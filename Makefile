# How to Make a Release
# ---------------------
#
# This file answers the question "how to make a release" hopefully
# better than a document does (only meejah and warner may currently do
# the "upload to PyPI" part anyway)
#

default:
	echo "see Makefile"

release-clean:
	@echo "Cleanup stale release: " `python newest-version.py`
	-rm NEWS.md.asc
	-rm dist/magic-wormhole-mailbox-server-`python newest-version.py`.tar.gz*
	-rm dist/magic_wormhole_mailbox_server-`python newest-version.py`-py3-none-any.whl*
	git tag -d `python newest-version.py`

# create a branch, like: git checkout -b prepare-release-0.16.0
# then run these, so CI can run on the release
release:
	@echo "Is checkout clean?"
	git diff-files --quiet
	git diff-index --quiet --cached HEAD --

	@echo "Install required build software"
	python -m pip install --editable .[dev,release]

	@echo "Test README"
	python setup.py check -s

	@echo "Is GPG Agent rubnning, and has key?"
	gpg --pinentry=loopback -u meejah@meejah.ca --armor --clear-sign NEWS.md

	@echo "Bump version and create tag"
	python update-version.py
#	python update-version.py --patch  # for bugfix release

	@echo "Build and sign wheel"
	python setup.py bdist_wheel
	gpg --pinentry=loopback -u meejah@meejah.ca --armor --detach-sign dist/magic_wormhole_mailbox_server-`git describe --abbrev=0`-py3-none-any.whl
	ls dist/*`git describe --abbrev=0`*

	@echo "Build and sign source-dist"
	python setup.py sdist
	gpg --pinentry=loopback -u meejah@meejah.ca --armor --detach-sign dist/magic-wormhole-mailbox-server-`git describe --abbrev=0`.tar.gz
	ls dist/*`git describe --abbrev=0`*

release-test:
	gpg --verify dist/magic-wormhole-mailbox-server-`git describe --abbrev=0`.tar.gz.asc
	gpg --verify dist/magic_wormhole_mailbox_server-`git describe --abbrev=0`-py3-none-any.whl.asc
	python -m venv testmf_venv
	testmf_venv/bin/pip install --upgrade pip
	testmf_venv/bin/pip install dist/magic_wormhole_mailbox_server-`git describe --abbrev=0`-py3-none-any.whl
	testmf_venv/bin/twistd wormhole-mailbox --version
	testmf_venv/bin/pip uninstall -y magic_wormhole_mailbox_server
	testmf_venv/bin/pip install dist/magic-wormhole-mailbox-server-`git describe --abbrev=0`.tar.gz
	testmf_venv/bin/twistd wormhole-mailbox --version
	rm -rf testmf_venv

release-upload:
	twine upload --username __token__ --password `cat PRIVATE-release-token` dist/magic_wormhole_mailbox_server-`git describe --abbrev=0`-py3-none-any.whl dist/magic_wormhole_mailbox_server-`git describe --abbrev=0`-py3-none-any.whl.asc dist/magic-wormhole-mailbox-server-`git describe --abbrev=0`.tar.gz dist/magic-wormhole-mailbox-server-`git describe --abbrev=0`.tar.gz.asc
	mv dist/*-`git describe --abbrev=0`.tar.gz.asc signatures/
	mv dist/*-`git describe --abbrev=0`-py3-none-any.whl.asc signatures/
	git add signatures/magic-wormhole-mailbox-server-`git describe --abbrev=0`.tar.gz.asc
	git add signatures/magic_wormhole_mailbox_server-`git describe --abbrev=0`-py3-none-any.whl.asc
	git commit -m "signatures for release"
	git push origin-push `git describe --abbrev=0`


dilation.png: dilation.seqdiag
	seqdiag --no-transparency -T png --size 1000x800 -o dilation.png
