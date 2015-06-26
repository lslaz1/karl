

define('jquery', [], function(){
    return window.jQuery;
});

require([
  'jquery',
  'mockup-patterns-tinymce',
  'pat-registry'
], function($, TinyMCE, Registry){
  $(document).ready(function(){
    Registry.scan($('body'));
  });
});