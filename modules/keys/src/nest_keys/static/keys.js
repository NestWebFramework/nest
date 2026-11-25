/* keys.js: the account's key. On /cheie, the code after # (never sent to the server by the
   browser) fills the form and is sent once, then removed from the address bar. Elsewhere:
   copy the link, save it as a file, share it (the phone's own sheet). No library. */
(function () {
  var form = document.querySelector("[data-key-form]");
  if (form && location.hash.length > 1) {
    var code = decodeURIComponent(location.hash.slice(1));
    history.replaceState(null, "", location.pathname + location.search);
    form.querySelector("input[name=cod]").value = code;
    form.submit();
  }
  var link = document.querySelector("[data-key-link]");
  var url = link ? link.getAttribute("href") : "";
  function done(button, text) {
    var was = button.textContent;
    button.textContent = text;
    setTimeout(function () { button.textContent = was; }, 2000);
  }
  document.querySelectorAll("[data-key-copy]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (navigator.clipboard) navigator.clipboard.writeText(url).then(function () { done(b, "✓"); });
    });
  });
  document.querySelectorAll("[data-key-download]").forEach(function (b) {
    b.addEventListener("click", function () {
      var code = (document.querySelector("[data-key-code]") || {}).textContent || "";
      var text = b.dataset.text + "\n\n" + url + "\n\n" + code + "\n";
      var a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
      a.download = b.dataset.file || "key.txt";
      document.body.appendChild(a);
      a.click();
      a.remove();
      done(b, "✓");
    });
  });
  document.querySelectorAll("[data-key-share]").forEach(function (b) {
    if (!navigator.share) return;
    b.hidden = false;
    b.addEventListener("click", function () { navigator.share({ url: url }).catch(function () {}); });
  });
})();

/* Passkeys (WebAuthn), with the browser's own API. A box marked data-passkeys carries the
   module's address (data-base), the form token (data-csrf) and the words to say. Buttons:
   data-passkey-enter (sign in: the device offers its passkeys for this site),
   data-passkey-register (protect this account). An input with autocomplete="webauthn"
   lets the browser offer a passkey as it is focused (conditional mediation). */
(function () {
  var box = document.querySelector("[data-passkeys]");
  if (!box) return;
  var supported = !!(window.PublicKeyCredential && navigator.credentials);
  box.querySelectorAll("[data-passkey-enter], [data-passkey-register]").forEach(function (b) {
    b.hidden = !supported;
  });
  if (!supported) {
    var none = box.querySelector("[data-passkey-none]");
    if (none) none.hidden = false;
    return;
  }
  var base = box.dataset.base, csrf = box.dataset.csrf;
  var say = box.querySelector("[data-passkey-say]");

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
  function post(path, body) {
    return fetch(base + path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(body || {}),
    }).then(function (r) { return r.json().then(function (j) { j.status = r.status; return j; }); });
  }
  function tell(key) {
    if (!say) return;
    say.textContent = box.dataset["msg" + key.charAt(0).toUpperCase() + key.slice(1)] || box.dataset.msgRefused || "";
    say.hidden = !say.textContent;
  }
  function common(cred) {
    return {
      id: cred.id,
      rawId: b64(cred.rawId),
      type: cred.type,
      authenticatorAttachment: cred.authenticatorAttachment || null,
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
    };
  }

  function enter(mediation, signal) {
    return post("/acces/optiuni").then(function (got) {
      var o = got.options;
      var publicKey = {
        challenge: unb64(o.challenge),
        rpId: o.rpId,
        timeout: o.timeout,
        userVerification: o.userVerification,
        allowCredentials: [],
      };
      var ask = { publicKey: publicKey };
      if (mediation) { ask.mediation = mediation; ask.signal = signal; }
      return navigator.credentials.get(ask).then(function (cred) {
        var c = common(cred);
        c.response = {
          clientDataJSON: b64(cred.response.clientDataJSON),
          authenticatorData: b64(cred.response.authenticatorData),
          signature: b64(cred.response.signature),
          userHandle: cred.response.userHandle ? b64(cred.response.userHandle) : null,
        };
        return post("/acces", { ticket: got.ticket, credential: c });
      });
    }).then(function (done) {
      if (done.ok) location.assign(done.go || "/");
      else tell(done.why || "refused");
    });
  }

  function register(button) {
    button.disabled = true;
    post("/acces/inregistrare/optiuni").then(function (got) {
      var o = got.options;
      var publicKey = {
        challenge: unb64(o.challenge),
        rp: o.rp,
        user: { id: unb64(o.user.id), name: o.user.name, displayName: o.user.displayName },
        pubKeyCredParams: o.pubKeyCredParams,
        timeout: o.timeout,
        attestation: o.attestation,
        authenticatorSelection: o.authenticatorSelection,
        excludeCredentials: (o.excludeCredentials || []).map(function (c) {
          return { id: unb64(c.id), type: c.type, transports: c.transports };
        }),
      };
      return navigator.credentials.create({ publicKey: publicKey }).then(function (cred) {
        var c = common(cred);
        c.response = {
          clientDataJSON: b64(cred.response.clientDataJSON),
          attestationObject: b64(cred.response.attestationObject),
          transports: cred.response.getTransports ? cred.response.getTransports() : [],
        };
        return post("/acces/inregistrare", { ticket: got.ticket, credential: c });
      });
    }).then(function (done) {
      if (done.ok) location.assign(base + "/cont");  // not a reload: it may resend a form
      else { tell(done.why || "refused"); button.disabled = false; }
    }).catch(function () { tell("cancelled"); button.disabled = false; });
  }

  var waiting = null;  // the conditional ask, stopped before a button's own
  box.querySelectorAll("[data-passkey-enter]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (waiting) waiting.abort();
      enter().catch(function () { tell("cancelled"); });
    });
  });
  box.querySelectorAll("[data-passkey-register]").forEach(function (b) {
    b.addEventListener("click", function () { register(b); });
  });
  var field = box.querySelector("input[autocomplete~=webauthn]");
  if (field && PublicKeyCredential.isConditionalMediationAvailable) {
    PublicKeyCredential.isConditionalMediationAvailable().then(function (yes) {
      if (!yes) return;
      waiting = new AbortController();
      enter("conditional", waiting.signal).catch(function () {});
    });
  }
})();
