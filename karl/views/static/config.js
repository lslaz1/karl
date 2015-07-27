/* RequireJS configuration
 */

/* global module:true */

(function() {
  'use strict';

  var getBaseUrl = function(){
    try{
      // won't work in generator scripts
      return $('#karl-static-url').attr('content');
    }catch(e){
      return '/static';
    }
  }
  var baseUrl = getBaseUrl();
  var tinymcePlugins = [
    'advlist', 'anchor', 'autolink', 'autoresize', 'autosave', 'bbcode',
    'charmap', 'code', 'colorpicker', 'contextmenu', 'directionality',
    'emoticons', 'fullpage', 'fullscreen', 'hr', 'image', 'importcss',
    'insertdatetime', 'layer', 'legacyoutput', 'link', 'lists', 'media',
    'nonbreaking', 'noneditable', 'pagebreak', 'paste', 'preview', 'print',
    'save', 'searchreplace', 'spellchecker', 'tabfocus', 'table', 'template',
    'textcolor', 'textpattern', 'visualblocks', 'visualchars', 'wordcount',
    'compat3x'
  ];

  var requirejsOptions = {
    baseUrl: baseUrl,
    optimize: 'none',
    paths: {
      'backbone': 'dist/backbone/backbone',
      'dropzone': 'dist/dropzone/dist/dropzone-amd-module',
      'jqtree': 'dist/jqtree/tree.jquery',
      'jquery': 'dist/jquery/jquery',
      'jquery.cookie': 'dist/jquery.cookie/jquery.cookie',
      'jquery.event.drag': 'dist/mockup/lib/jquery.event.drag',
      'jquery.event.drop': 'dist/mockup/lib/jquery.event.drop',
      'jquery.form': 'dist/jquery-form/jquery.form',
      'translate': 'dist/mockup/js/i18n-wrapper',
      'mockup-i18n': 'dist/mockup/js/i18n',
      'mockup-parser': 'dist/mockup-core/js/parser',

      'mockup-patterns-base': 'dist/mockup-core/js/pattern',
      'mockup-patterns-backdrop': 'dist/mockup/patterns/backdrop/pattern',
      'mockup-patterns-modal': 'dist/mockup/patterns/modal/pattern',
      'mockup-patterns-autotoc': 'dist/mockup/patterns/autotoc/pattern',
      'mockup-patterns-relateditems': 'dist/mockup/patterns/relateditems/pattern',
      'mockup-patterns-select2': 'dist/mockup/patterns/select2/pattern',
      'mockup-patterns-sortable': 'dist/mockup/patterns/sortable/pattern',
      'mockup-patterns-tinymce': 'dist/mockup/patterns/tinymce/pattern',
      'mockup-patterns-tinymce-url': 'dist/mockup/patterns/tinymce',
      'mockup-patterns-tree': 'dist/mockup/patterns/tree/pattern',
      'mockup-patterns-upload': 'dist/mockup/patterns/upload/pattern',
      'mockup-patterns-upload-url': 'dist/mockup/patterns/upload',

      'mockup-ui-url': 'dist/mockup/js/ui',
      'mockup-utils': 'dist/mockup/js/utils',
      'mockup-router': 'dist/mockup/js/router',
      'select2': 'dist/select2/select2',
      'text': 'dist/requirejs-text/text',
      'tinymce': 'dist/tinymce-builded/js/tinymce/tinymce',
      'tinymce-modern-theme': 'dist/tinymce-builded/js/tinymce/themes/modern/theme',
      'underscore': 'dist/lodash/dist/lodash.underscore',

      // Patternslib
      'pat-compat': 'dist/patternslib/src/core/compat',
      'pat-jquery-ext': 'dist/patternslib/src/core/jquery-ext',
      'pat-logger': 'dist/patternslib/src/core/logger',
      'pat-registry': 'dist/patternslib/src/core/registry',
      'pat-utils': 'dist/patternslib/src/core/utils',
      'logging': 'dist/logging/src/logging'
    },
    shim: {
      'jqtree': { deps: ['jquery'] },
      'jquery.event.drag': { deps: ['jquery'] },
      'jquery.event.drop': { deps: ['jquery'], exports: '$.drop' },
      'tinymce': {
        exports: 'window.tinyMCE',
        init: function () {
          this.tinyMCE.DOM.events.domLoaded = true;
          return this.tinyMCE;
        }
      },
      'tinymce-modern-theme': { deps: ['tinymce'] },
      'underscore': { exports: 'window._' }
    },
    wrapShim: true
  };
  for(var i=0; i<tinymcePlugins.length; i=i+1){
    var plugin = tinymcePlugins[i];
    requirejsOptions.paths['tinymce-' + plugin] = baseUrl + '/dist/tinymce-builded/js/tinymce/plugins/' + plugin + '/plugin';
    requirejsOptions.shim['tinymce-' + plugin] = {
      deps: ['tinymce']
    };
  }

  if (typeof exports !== 'undefined' && typeof module !== 'undefined') {
    module.exports = requirejsOptions;
  }
  if (typeof requirejs !== 'undefined' && requirejs.config) {
    requirejs.config(requirejsOptions);
  }

}());
