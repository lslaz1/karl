
NPM = npm
BOWER = ./node_modules/bower/bin/bower
NODE_PATH = ./node_modules
GULP = ./node_modules/.bin/gulp


install:
	$(NPM) install
	NODE_PATH=$(NODE_PATH) $(BOWER) install --config.interactive=0

npm:
	$(NPM) install

copy:
	$(GULP) copy


bower:
	NODE_PATH=$(NODE_PATH) $(BOWER) install --config.interactive=0
	$(GULP) copy

js:
	$(GULP) process-js

css:
	$(GULP) process-css

watch-css:
	$(GULP) watch-css