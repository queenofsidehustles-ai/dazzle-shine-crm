/* Make a camera photo small enough to send from a phone.
 *
 * A phone's camera makes a picture of several megabytes. Sent as it is, over a
 * cellular connection from a client's driveway or a basement, that is a
 * minute of waiting, and the server gives up on a request that long (and the
 * phone often gives up first). A cleaning photo has to show the room, not
 * every pore on the wall: 1600 pixels on the long side is plenty and comes
 * to a few hundred kilobytes.
 *
 *   AkyePhoto.shrink(file)  ->  Promise of a File: smaller if it could be made
 *                               smaller, otherwise the file you gave it.
 *
 * It never stops an upload. A browser that cannot decode the picture (some
 * HEIC), a canvas that will not draw, anything at all going wrong: the
 * original goes through, as it did before this existed.
 */
(function (global) {
  var LONG_SIDE = 1600;       // pixels
  var QUALITY = 0.82;         // JPEG
  var LEAVE_ALONE = 400 * 1024;   // already small: not worth re-encoding

  function decode(file) {
    if (global.createImageBitmap) {
      // from-image: turn it the way the phone was held, as the camera app does.
      return global.createImageBitmap(file, { imageOrientation: 'from-image' })
        .catch(function () { return global.createImageBitmap(file); });
    }
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error('cannot decode')); };
      img.src = url;
    });
  }

  function shrink(file) {
    try {
      if (!file || !/^image\//i.test(file.type || '') || file.size <= LEAVE_ALONE) {
        return Promise.resolve(file);
      }
      return decode(file).then(function (img) {
        var w = img.width || img.naturalWidth, h = img.height || img.naturalHeight;
        if (!w || !h) return file;
        var scale = Math.min(1, LONG_SIDE / Math.max(w, h));
        var cw = Math.max(1, Math.round(w * scale)), ch = Math.max(1, Math.round(h * scale));
        var canvas = document.createElement('canvas');
        canvas.width = cw; canvas.height = ch;
        var ctx = canvas.getContext('2d');
        if (!ctx) return file;
        ctx.drawImage(img, 0, 0, cw, ch);
        if (img.close) img.close();
        return new Promise(function (resolve) {
          canvas.toBlob(function (blob) {
            if (!blob || blob.size >= file.size) { resolve(file); return; }
            var name = (file.name || 'photo').replace(/\.[^.]+$/, '') + '.jpg';
            resolve(new File([blob], name, { type: 'image/jpeg' }));
          }, 'image/jpeg', QUALITY);
        });
      }).catch(function () { return file; });
    } catch (e) {
      return Promise.resolve(file);
    }
  }

  global.AkyePhoto = { shrink: shrink, LONG_SIDE: LONG_SIDE };
})(window);
