/**
 * Photos annonce : aperçus locaux, suppression, glisser-déposer, synchro du champ file avant envoi.
 */
(function () {
  var ACCEPT = ["image/jpeg", "image/png", "image/webp", "image/gif"];
  var ACCEPT_EXT = { jpg: 1, jpeg: 1, png: 1, webp: 1, gif: 1 };

  function extOf(name) {
    if (!name || name.indexOf(".") === -1) return "";
    return name.split(".").pop().toLowerCase();
  }

  function isAllowedFile(file) {
    if (file.type && ACCEPT.indexOf(file.type) !== -1) return true;
    return !!ACCEPT_EXT[extOf(file.name)];
  }

  function keyFor(f) {
    return f.name + "|" + f.size + "|" + f.lastModified;
  }

  function setFilesOnInput(input, files) {
    var dt = new DataTransfer();
    for (var i = 0; i < files.length; i++) dt.items.add(files[i]);
    input.files = dt.files;
  }

  function init() {
    var form = document.getElementById("listingForm");
    var input = document.getElementById("images");
    var dropzone = document.getElementById("listingPhotoDropzone");
    var previews = document.getElementById("listingPhotoPreviews");
    var hint = document.getElementById("fileListHint");
    if (!form || !input || !dropzone || !previews) return;

    var zone = dropzone.closest(".listing-photos");
    var files = [];

    function syncHint() {
      if (!hint) return;
      if (!files.length) {
        hint.textContent = "";
        return;
      }
      hint.textContent = files.length + " photo(s) prête(s) à l’envoi.";
    }

    function revokeAllUrls() {
      previews.querySelectorAll("img[data-blob-url]").forEach(function (img) {
        var u = img.getAttribute("data-blob-url");
        if (u) URL.revokeObjectURL(u);
      });
    }

    function render() {
      revokeAllUrls();
      previews.innerHTML = "";
      files.forEach(function (file, index) {
        var url = URL.createObjectURL(file);
        var wrap = document.createElement("div");
        wrap.className = "listing-photos__tile";
        wrap.setAttribute("role", "group");
        wrap.setAttribute("aria-label", "Aperçu " + (index + 1));

        var img = document.createElement("img");
        img.src = url;
        img.alt = "";
        img.className = "listing-photos__thumb";
        img.setAttribute("data-blob-url", url);

        var rm = document.createElement("button");
        rm.type = "button";
        rm.className = "listing-photos__remove";
        rm.setAttribute("aria-label", "Retirer cette photo");
        rm.textContent = "×";
        rm.addEventListener("click", function () {
          var ix = files.indexOf(file);
          if (ix !== -1) files.splice(ix, 1);
          setFilesOnInput(input, files);
          render();
          syncHint();
        });

        wrap.appendChild(img);
        wrap.appendChild(rm);
        previews.appendChild(wrap);
      });
      syncHint();
    }

    function addFileList(list) {
      var seen = {};
      files.forEach(function (f) {
        seen[keyFor(f)] = true;
      });
      var rejected = 0;
      for (var i = 0; i < list.length; i++) {
        var f = list[i];
        if (!isAllowedFile(f)) {
          rejected++;
          continue;
        }
        var k = keyFor(f);
        if (seen[k]) continue;
        seen[k] = true;
        files.push(f);
      }
      setFilesOnInput(input, files);
      render();
      if (rejected && hint) {
        hint.textContent =
          files.length +
          " photo(s) — " +
          rejected +
          " fichier(s) ignoré(s) (formats : JPG, PNG, WEBP, GIF).";
      }
    }

    input.addEventListener("change", function () {
      if (input.files && input.files.length) addFileList(input.files);
      input.value = "";
    });

    if (zone) {
      zone.addEventListener("dragenter", function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.add("is-dragover");
      });
      zone.addEventListener("dragover", function (e) {
        e.preventDefault();
        e.stopPropagation();
      });
      zone.addEventListener("dragleave", function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (zone.contains(e.relatedTarget)) return;
        dropzone.classList.remove("is-dragover");
      });
      zone.addEventListener("drop", function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.remove("is-dragover");
        var dt = e.dataTransfer;
        if (!dt || !dt.files || !dt.files.length) return;
        addFileList(dt.files);
      });
    }

    form.addEventListener("submit", function (e) {
      if (!files.length) {
        e.preventDefault();
        alert(
          "Veuillez ajouter au moins une photo (JPG, PNG, WEBP ou GIF) avant d’envoyer le formulaire."
        );
        input.focus();
        return false;
      }
      setFilesOnInput(input, files);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      init();
    });
  } else {
    init();
  }
})();
