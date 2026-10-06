/* Loads the Google Maps JavaScript API synchronously so maps can be built on first paint.
   gm_authFailure fires when Google rejects the key; every map then swaps itself to Leaflet. */
window.MAARG_GM = { failed: false, handlers: [] };
(function () {
  var k = window.MAARG_CONFIG && MAARG_CONFIG.GOOGLE_MAPS_API_KEY;
  if (!k) return;
  window.gm_authFailure = function () { MAARG_GM.failed = true; MAARG_GM.handlers.splice(0).forEach(function (f) { try { f(); } catch (e) { } }); };
  document.write('<script src="https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(k) + '&v=weekly&language=en"><\/script>');
})();
