Vendored PyZOGY (https://github.com/dguevel/PyZOGY, commit 0f13f98, MIT License, (c) 2017 dguevel).
PyZOGY is not on PyPI and its setup.py entry point is malformed, so it is bundled to make
`pip install lcogtsnpipe-ai` work. Only the import of `util` in image_class.py was made relative.
snpipe.diff replaces `util.interpolate_bad_pixels` at run time by an exactly equivalent faster filter.
