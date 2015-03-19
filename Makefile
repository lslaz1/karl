
NPM = npm
BOWER = ./node_modules/bower/bin/bower
NODE_PATH = ./node_modules
GULP = ./node_modules/.bin/gulp


install:
	$(NPM) install
	NODE_PATH=$(NODE_PATH) $(BOWER) install --config.interactive=0

copy:
	$(GULP) copy


build-js:
	$(GULP) process-js