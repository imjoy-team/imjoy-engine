pip install twine
rm ./dist/*
python setup.py sdist bdist_wheel
twine upload dist/*
