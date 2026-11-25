/* keys.js: the keys pages' buttons, with the browser's own APIs (no library).
   - /cheie: the code after # (never sent to the server) fills the form and is sent once;
   - the key page: download the key as a small file, or copy its link;
   - the account: "Download a key" makes a new one and downloads it at once;
   - passkeys: sign in (data-passkey-enter) or keep the account with this device
     (data-passkey-register); the box (data-passkeys) carries the module's address, the
     form token and the words to say. */
(function () {
  var form = document.querySelector("[data-key-form]");
  if (form && location.hash.length > 1) {
    var code = decodeURIComponent(location.hash.slice(1));
    history.replaceState(null, "", location.pathname + location.search);
    form.querySelector("input[name=cod]").value = code;
    form.submit();
  }

  var box = document.querySelector("[data-passkeys]");
  var base = box ? box.dataset.base : "";
  var csrf = box ? box.dataset.csrf : "";
  var say = document.querySelector("[data-passkey-say]");

  function tell(key) {
    if (!say || !box) return;
    say.textContent = box.dataset["msg" + key.charAt(0).toUpperCase() + key.slice(1)] || box.dataset.msgRefused || "";
    say.hidden = !say.textContent;
  }
  function post(path, body) {
    return fetch(base + path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(body || {}),
    }).then(function (r) { return r.json(); });
  }
  function saveFile(name, text) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
  function done(button) {
    if (button.textContent.indexOf("✓") < 0) button.textContent += " ✓";
  }

  // the key page: the key shown, to download or copy
  var link = document.querySelector("[data-key-link]");
  var url = link ? link.getAttribute("href") : "";
  document.querySelectorAll("[data-key-download]").forEach(function (b) {
    b.addEventListener("click", function () {
      var code = (document.querySelector("[data-key-code]") || {}).textContent || "";
      saveFile(b.dataset.file || "key.txt", b.dataset.text + "\n\n" + url + "\n\n" + code + "\n");
      done(b);
    });
  });
  document.querySelectorAll("[data-key-copy]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (navigator.clipboard) navigator.clipboard.writeText(url).then(function () { done(b); });
    });
  });
  // the account: a new key, downloaded at once
  document.querySelectorAll("[data-key-new]").forEach(function (b) {
    b.addEventListener("click", function () {
      b.disabled = true;
      post("/cheie/noua.json").then(function (k) {
        saveFile(b.dataset.file || "key.txt", b.dataset.text + "\n\n" + k.link + "\n\n" + k.code + "\n");
        location.reload();
      }).catch(function () { b.disabled = false; tell("refused"); });
    });
  });

  // passkeys
  if (!box) return;
  var supported = !!(window.PublicKeyCredential && navigator.credentials);
  box.querySelectorAll("[data-passkey-enter], [data-passkey-register]").forEach(function (b) { b.hidden = !supported; });
  if (!supported) return;

  function b64(buf) {
    var s = "", bytes = new Uint8Array(buf);
    for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function unb64(text) {
    var s = atob(text.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((text.length + 3) % 4));
    var bytes = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) bytes[i] = s.charCodeAt(i);
    return bytes.buffer;
  }
  function common(cred) {
    return {
      id: cred.id, rawId: b64(cred.rawId), type: cred.type,
      authenticatorAttachment: cred.authenticatorAttachment || null,
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
    };
  }
  box.querySelectorAll("[data-passkey-enter]").forEach(function (b) {
    b.addEventListener("click", function () {
      post("/acces/optiuni").then(function (got) {
        var o = got.options;
        return navigator.credentials.get({ publicKey: {
          challenge: unb64(o.challenge), rpId: o.rpId, timeout: o.timeout,
          userVerification: o.userVerification, allowCredentials: [],
        } }).then(function (cred) {
          var c = common(cred);
          c.response = {
            clientDataJSON: b64(cred.response.clientDataJSON),
            authenticatorData: b64(cred.response.authenticatorData),
            signature: b64(cred.response.signature),
            userHandle: cred.response.userHandle ? b64(cred.response.userHandle) : null,
          };
          return post("/acces", { ticket: got.ticket, credential: c });
        });
      }).then(function (r) {
        if (r.ok) location.assign(r.go || "/");
        else tell(r.why || "refused");
      }).catch(function () { tell("cancelled"); });
    });
  });
  box.querySelectorAll("[data-passkey-register]").forEach(function (b) {
    b.addEventListener("click", function () {
      b.disabled = true;
      post("/acces/inregistrare/optiuni").then(function (got) {
        var o = got.options;
        return navigator.credentials.create({ publicKey: {
          challenge: unb64(o.challenge), rp: o.rp,
          user: { id: unb64(o.user.id), name: o.user.name, displayName: o.user.displayName },
          pubKeyCredParams: o.pubKeyCredParams, timeout: o.timeout, attestation: o.attestation,
          authenticatorSelection: o.authenticatorSelection,
          excludeCredentials: (o.excludeCredentials || []).map(function (c) { return { id: unb64(c.id), type: c.type }; }),
        } }).then(function (cred) {
          var c = common(cred);
          c.response = {
            clientDataJSON: b64(cred.response.clientDataJSON),
            attestationObject: b64(cred.response.attestationObject),
            transports: cred.response.getTransports ? cred.response.getTransports() : [],
          };
          return post("/acces/inregistrare", { ticket: got.ticket, credential: c });
        });
      }).then(function (r) {
        if (r.ok) location.reload();
        else { tell(r.why || "refused"); b.disabled = false; }
      }).catch(function () { tell("cancelled"); b.disabled = false; });
    });
  });
})();
