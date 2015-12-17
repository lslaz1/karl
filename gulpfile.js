
/* jshint node: true */
'use strict';

var _ = require('lodash'),
    path = require('path'),
    gulp = require('gulp'),
    plugins = require('gulp-load-plugins')(),
    util = require('gulp-util'),
    fs = require('fs'),
    karma = require('karma').server,
    browserSync = require("browser-sync"),
    minifyCSS = require('gulp-minify-css'),
    less = require('gulp-less'),
    rjs = require('gulp-requirejs');

  var livereload = require('gulp-livereload');
  var LessPluginInlineUrls = require('less-plugin-inline-urls');
  var requirejsOptions = require('./karl/views/static/config');
  requirejsOptions.baseUrl = './karl/views/static/';
  requirejsOptions.out = 'tinymce.min.js';
  requirejsOptions.name = '../../../node_modules/almond/almond';
  requirejsOptions.include = 'tinymce.js';
  requirejsOptions.mainConfigFile = './karl/views/static/config.js';
  requirejsOptions.stubModules = ['jquery'];
  requirejsOptions.optimize = 'uglify';
  /* fix tinymce plugin paths */
  _.forEach(requirejsOptions.paths, function(path, name){
    if(path.indexOf('/static/dist/tinymce-builded/js/tinymce/plugins') !== -1){
      requirejsOptions.paths[name] = path.replace(
        '/static/dist/tinymce-builded/js/tinymce/plugins',
        'dist/tinymce-builded/js/tinymce/plugins');
    }
  });

var res = require('./karl/views/static/resources.json');

var banner =  '/*\n * KARL <%= fullName %> generated resources http://github.com/karlproject/karl %>\n*/\n';
var stampfile =  'KARL resources generated at <%= new Date().toISOString() %>\n';

function staticPaths(items) {
  return _.map(items, function(name) {
    return res.staticPrefix + name;
  });
}

function destPrefix(name) {
  // hardwire tinymce destination from here,
  // as it's simpler than putting it to the json file.
  return res.minPrefix;
}

function destFolder(name) {
  return res.staticPrefix + destPrefix(name);
}

gulp.task('stamp', function() {
  fs.writeFile(res.staticPrefix + 'dist/stampfile', _.template(stampfile)());
});

var tocopy = ['jquery', 'jquery-ui', 'tinymce-builded', 'lodash', 'patternslib',
              'logging', 'jqtree', 'dropzone', 'mockup-core', 'select2', 'requirejs-text',
              'requirejs', 'jquery-form', 'backbone', 'bootstrap',
              'datatables.net', 'datatables.net-dt',
              'datatables.net-responsive', 'datatables.net-responsive-dt',
              'datatables.net-buttons', 'datatables.net-buttons-dt',
              'datatables.net-scroller', 'datatables.net-scroller-dt'];

gulp.task('copy', function() {
  for(var i=0; i<tocopy.length; i++){
    gulp.src(['./bower_components/' + tocopy[i] + '/**/*'])
      .pipe(gulp.dest(res.staticPrefix + 'dist/' + tocopy[i]));
  }

  gulp.src(['./bower_components/jquery-ui/ui/**/*'])
    .pipe(gulp.dest(res.staticPrefix + 'dist/jquery-ui/ui/'));
  gulp.src(['./bower_components/bgiframe/jquery.bgiframe.js'])
    .pipe(gulp.dest(res.staticPrefix + 'dist/jquery-ui/external/'));
  gulp.src(['./bower_components/jquery-ui/themes/base/**/*'])
    .pipe(gulp.dest(res.staticPrefix + 'dist/jquery-ui/themes/base/'));
  gulp.src(['./bower_components/mockup/mockup/**/*'])
    .pipe(gulp.dest(res.staticPrefix + 'dist/mockup/'));

  /* fonts */
  gulp.src(['./bower_components/tinymce-builded/js/tinymce/skins/lightgray/fonts/*'])
    .pipe(gulp.dest(res.staticPrefix + 'fonts/'));

  /* select2 files */
  gulp.src(['./bower_components/select2/select2-spinner.gif'])
    .pipe(gulp.dest(res.staticPrefix));
  gulp.src(['./bower_components/select2/select2.png'])
    .pipe(gulp.dest(res.staticPrefix));
});

gulp.task('process-js', function () {
  _.each(res.js, function(items, name) {
    var fullName = name + '.min.js';
    var dest = destFolder(name);
    gulp.src(staticPaths(items))
      .pipe(plugins.sourcemaps.init())
        .pipe(plugins.concat(fullName))
        .pipe(plugins.removeUseStrict())
        .pipe(plugins.uglify())
        .pipe(plugins.header(_.template(banner, {fullName: fullName})))
      .pipe(plugins.sourcemaps.write('./'))
      .pipe(gulp.dest(dest));
    util.log('Producing', util.colors.green(destFolder(name) + fullName));
  });
  rjs(requirejsOptions)
  .pipe(gulp.dest('./karl/views/static')); // pipe it to the output DIR 
});

gulp.task('process-css', function () {
  _.each(res.css, function(name) {
    gulp.src(res.staticPrefix + name + '.less')
      .pipe(less({
        plugins: [LessPluginInlineUrls]
      }))
      .pipe(minifyCSS())
      .pipe(gulp.dest(res.staticPrefix))
      .pipe(livereload());
    util.log('Producing', util.colors.green(res.staticPrefix + name));
  });
});

gulp.task('watch-css', function() {
  _.each(res.css, function(name) {
    gulp.watch(res.staticPrefix + name + '.less', ['process-css']);
  });
  gulp.watch(res.staticPrefix + '/dist/mockup/patterns/**/*.less', ['process-css']);
});

gulp.task('unit', function (done) {
  karma.start({
    configFile: __dirname + '/karma.conf.js',
    singleRun: true,
    detectBrowsers: {
      enabled: true,
      phantomJs: true,
    },
  }, done);
});

gulp.task('autounit', function (done) {
  karma.start({
    configFile: __dirname + '/karma.conf.js',
    singleRun: false,
    autoWatch: true,
  }, done);
});

gulp.task('e2e', function (done) {
  gulp.src(['./frontend-test/e2e/**/*-scenario.js'])
  .pipe(plugins.protractor.protractor({
    configFile: 'protractor.conf.js',
    args: []
  }))
  .on('error', function(e) {
    throw e;
  });
});

gulp.task('e2e-debug', function (done) {
  gulp.src(['./frontend-test/e2e/**/*-scenario.js'])
  .pipe(plugins.protractor.protractor({
    configFile: 'protractor.conf.js',
    args: ['debug']
  }))
  .on('error', function(e) {
    throw e;
  });
});

gulp.task('devmode', function() {
    browserSync({
        proxy: 'http://karl.127.0.0.1.xip.io:6543/',
        xip: true
    });
});


gulp.task('install', ['copy', 'process-js', 'process-css', 'stamp']);
gulp.task('default', ['devmode']);
