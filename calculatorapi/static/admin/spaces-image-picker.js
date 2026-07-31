/*
 * Admin "choose an existing image" picker.
 *
 * Each image field on a change form renders a .spaces-picker block (see
 * templates/admin/widgets/spaces_image_picker.html). Clicking its Browse button
 * opens a shared modal listing what is already in the media bucket, fetched from
 * /admin/image-library/. Clicking a thumbnail writes that image's bucket key
 * into the block's hidden input; SpacesImagePickerForm applies it on save.
 *
 * Plain ES5-ish DOM code on purpose: the admin has no bundler, and unfold ships
 * Alpine.js but nothing here needs it.
 *
 * Listings are small (the whole bucket is ~1k files) so search filters
 * client-side after a single fetch per folder. Thumbnails are loading="lazy"
 * so opening a 500-image folder doesn't fetch 500 images from the CDN.
 */
(function () {
  "use strict";

  var modal = null; // built once, on first use, shared by every field
  var activeBlock = null; // the .spaces-picker that opened the modal
  var cache = {}; // prefix -> image array, so reopening is instant
  var allImages = []; // images currently loaded in the modal

  // ── Modal construction ────────────────────────────────────────────────

  function buildModal() {
    var el = document.createElement("div");
    el.className = "spaces-modal";
    el.hidden = true;
    el.innerHTML = [
      '<div class="spaces-modal__panel" role="dialog" aria-modal="true" aria-label="Image library">',
      '  <div class="spaces-modal__head">',
      '    <span class="spaces-modal__title">Image library</span>',
      '    <select class="spaces-modal__folder" data-role="folder"></select>',
      '    <input type="search" class="spaces-modal__search" data-role="search" placeholder="Search by file name...">',
      '    <span class="spaces-modal__count" data-role="count"></span>',
      '    <button type="button" class="spaces-modal__refresh" data-role="refresh" title="Reload from the bucket">',
      '      <span class="material-symbols-outlined">refresh</span></button>',
      '    <button type="button" class="spaces-modal__close" data-role="close" title="Close">',
      '      <span class="material-symbols-outlined">close</span></button>',
      "  </div>",
      '  <div class="spaces-modal__body"><div class="spaces-modal__grid" data-role="grid"></div>',
      '    <div class="spaces-modal__message" data-role="message" hidden></div>',
      "  </div>",
      "</div>",
    ].join("");
    document.body.appendChild(el);

    el.querySelector('[data-role="close"]').addEventListener("click", closeModal);
    el.querySelector('[data-role="search"]').addEventListener("input", render);
    el.querySelector('[data-role="folder"]').addEventListener("change", function () {
      load(this.value, false);
    });
    el.querySelector('[data-role="refresh"]').addEventListener("click", function () {
      load(el.querySelector('[data-role="folder"]').value, true);
    });
    // Click the backdrop (but not the panel) to dismiss.
    el.addEventListener("click", function (event) {
      if (event.target === el) closeModal();
    });
    return el;
  }

  function closeModal() {
    if (modal) modal.hidden = true;
    activeBlock = null;
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && modal && !modal.hidden) closeModal();
  });

  // ── Data loading ──────────────────────────────────────────────────────

  function load(prefix, forceRefresh) {
    var grid = modal.querySelector('[data-role="grid"]');
    var message = modal.querySelector('[data-role="message"]');
    var folder = modal.querySelector('[data-role="folder"]');

    // Keep the dropdown honest about what is on screen. Needed on the cached
    // path below too: reopening from a different field changes the folder
    // without any fetch, so populateFolders() never runs to sync it.
    if (folder.dataset.filled === "1") folder.value = prefix;

    if (!forceRefresh && cache[prefix]) {
      allImages = cache[prefix];
      render();
      return;
    }

    grid.innerHTML = "";
    message.hidden = false;
    message.textContent = "Loading...";

    var url =
      activeBlock.dataset.endpoint +
      "?prefix=" +
      encodeURIComponent(prefix) +
      (forceRefresh ? "&refresh=1" : "");

    fetch(url, { credentials: "same-origin" })
      .then(function (response) {
        // admin_view() redirects an expired session to the login page, which
        // arrives here as an HTML 200 — treat anything non-JSON as a failure
        // rather than letting response.json() throw an opaque parse error.
        var type = response.headers.get("content-type") || "";
        if (!response.ok || type.indexOf("application/json") === -1) {
          throw new Error("Could not load the image library.");
        }
        return response.json();
      })
      .then(function (data) {
        if (data.available === false) {
          throw new Error("Could not reach the image storage bucket.");
        }
        allImages = data.images || [];
        cache[prefix] = allImages;
        populateFolders(data.folders || [], prefix);
        render();
      })
      .catch(function (error) {
        allImages = [];
        grid.innerHTML = "";
        message.hidden = false;
        message.textContent =
          error.message + " You can still upload a file from your computer.";
      });
  }

  function populateFolders(folders, current) {
    var select = modal.querySelector('[data-role="folder"]');
    if (select.dataset.filled === "1") {
      select.value = current;
      return;
    }
    folders.forEach(function (folder) {
      var option = document.createElement("option");
      option.value = folder;
      option.textContent = folder.replace(/\/$/, "").replace(/_/g, " ");
      select.appendChild(option);
    });
    select.dataset.filled = "1";
    select.value = current;
  }

  // ── Rendering ─────────────────────────────────────────────────────────

  function render() {
    var grid = modal.querySelector('[data-role="grid"]');
    var message = modal.querySelector('[data-role="message"]');
    var count = modal.querySelector('[data-role="count"]');
    var term = modal.querySelector('[data-role="search"]').value.trim().toLowerCase();

    var matches = allImages.filter(function (image) {
      return !term || image.name.toLowerCase().indexOf(term) !== -1;
    });

    grid.innerHTML = "";
    count.textContent = matches.length + " of " + allImages.length;

    if (!matches.length) {
      message.hidden = false;
      message.textContent = allImages.length
        ? "No file names match that search."
        : "This folder has no images yet.";
      return;
    }
    message.hidden = true;

    // One fragment, one reflow — a 500-image folder renders in a single paint.
    var fragment = document.createDocumentFragment();
    matches.forEach(function (image) {
      var button = document.createElement("button");
      button.type = "button"; // never submit the change form
      button.className = "spaces-modal__item";
      button.title = image.key;

      var img = document.createElement("img");
      img.src = image.url;
      img.alt = image.name;
      img.loading = "lazy";

      var label = document.createElement("span");
      label.textContent = image.name;

      button.appendChild(img);
      button.appendChild(label);
      button.addEventListener("click", function () {
        choose(image);
      });
      fragment.appendChild(button);
    });
    grid.appendChild(fragment);
  }

  // ── Selection ─────────────────────────────────────────────────────────

  function choose(image) {
    var block = activeBlock;
    if (!block) return;

    block.querySelector('[data-role="key"]').value = image.key;

    var chosen = block.querySelector('[data-role="chosen"]');
    chosen.querySelector('[data-role="chosen-thumb"]').src = image.url;
    chosen.querySelector('[data-role="chosen-name"]').textContent = image.name;
    chosen.hidden = false;

    // A pending file upload would win over this pick on the server, so clear
    // it to keep the form honest about what is actually going to be saved.
    var fileInput = document.getElementById(block.dataset.fileInput);
    if (fileInput) fileInput.value = "";

    closeModal();
  }

  function clearChoice(block) {
    block.querySelector('[data-role="key"]').value = "";
    block.querySelector('[data-role="chosen"]').hidden = true;
  }

  // ── Wiring ────────────────────────────────────────────────────────────

  function init() {
    document.querySelectorAll(".spaces-picker").forEach(function (block) {
      block.querySelector('[data-role="open"]').addEventListener("click", function () {
        if (!modal) modal = buildModal();
        activeBlock = block;
        modal.hidden = false;
        modal.querySelector('[data-role="search"]').value = "";
        load(block.dataset.prefix, false);
        modal.querySelector('[data-role="search"]').focus();
      });

      block.querySelector('[data-role="clear"]').addEventListener("click", function () {
        clearChoice(block);
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
