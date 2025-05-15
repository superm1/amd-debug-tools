build:
	python3 -m build
check:
	pytest
coverage:
	coverage run -m unittest
	coverage report
clean:
	rm -rf build src/*.egg-info build dist amd*.txt amd*md amd*html
