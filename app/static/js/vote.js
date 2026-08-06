/* Public Perception Index — community sentiment voting.
 *
 * The ballot is the marker on the published gauge: you drag it to where you
 * think the week sits and press the button under it. There is no separate
 * dialog, because the question ("where does this week sit on this scale?") is
 * already drawn on the page — asking it again in a modal made the reader
 * answer an abstract 1-to-10 instead of the scale they were looking at.
 *
 * The anonymous voter token is a random UUID with no derivation from anything
 * about the device or the person. It is written to localStorage only at the
 * moment someone actually votes: a reader who never votes leaves no trace, so
 * merely viewing the page stores nothing. Withdrawing a vote removes the token
 * as well, which is what makes "withdraw" mean withdrawn rather than hidden.
 */
(function () {
  'use strict';

  var API = '/api/hormuz-index/sentiment';
  var TOKEN_KEY = 'hmx_voter_token';

  var block = document.getElementById('ppi-block');
  if (!block) return;

  var track = document.getElementById('ppi-meter');
  var pointer = document.getElementById('ppi-pointer');
  var fillEl = document.getElementById('ppi-fill');
  var submitBtn = document.getElementById('ppi-submit');
  var submitLabel = document.getElementById('ppi-submit-label');
  var withdrawBtn = document.getElementById('ppi-withdraw');
  var hintEl = document.getElementById('ppi-hint');
  var hintText = document.getElementById('ppi-hint-text');
  var errorEl = document.getElementById('ppi-error');

  var valueEl = document.getElementById('ppi-value');
  var levelEl = document.getElementById('ppi-level');
  var countEl = document.getElementById('ppi-count');
  var gapEl = document.getElementById('ppi-gap');

  if (!track || !pointer || !submitBtn) return;

  var RATING_MIN = 1;
  var RATING_MAX = 10;
  var SCALE_MIN = 100;
  var SCALE_MAX = 200;
  /* Two decimals over a span of nine is ~900 positions, which no drag can
     distinguish from continuous. Matches votes.RATING_DP on the server. */
  var RATING_DP = 2;

  var modelScore = parseFloat(block.dataset.modelScore) || SCALE_MIN;

  var available = block.dataset.available !== 'false';
  var crowdPct = null;   // where the published aggregate sits, 0-100
  var myVote = null;     // this browser's recorded rating, or null
  var draft = null;      // dragged-but-unsent rating, or null
  var sending = false;

  /* Responses can land out of order: a vote posted while the page-load refresh
     is still in flight would otherwise be overwritten by that older, pre-vote
     aggregate. Only ever render a response newer than the last one drawn. */
  var issued = 0;
  var rendered = 0;

  /* One phrase per decile, escalation-ordered, so the marker reads as a
     judgement about the situation rather than an abstract number out of ten. */
  var WORDS = [
    '',                          // index 0 unused; ratings start at 1
    'Calm — business as usual',
    'Background friction',
    'Rising rhetoric',
    'Elevated tension',
    'Serious escalation risk',
    'Tense standoff',
    'Shipping under threat',
    'On the brink',
    'Conflict under way',
    'Open war'
  ];

  function wordFor(rating) {
    return WORDS[Math.min(RATING_MAX, Math.max(RATING_MIN, Math.round(rating)))];
  }

  function clamp(n, lo, hi) { return n < lo ? lo : (n > hi ? hi : n); }

  function round(n) {
    var f = Math.pow(10, RATING_DP);
    return Math.round(n * f) / f;
  }

  /* Rating, track position and index scale are three views of one number: the
     gauge spans 100-200 and the ballot spans 1-10 over exactly that range, so
     a percentage along the track *is* the vote. That equivalence is the whole
     reason the control can be the gauge. */
  function pctForRating(rating) {
    return (rating - RATING_MIN) / (RATING_MAX - RATING_MIN) * 100;
  }

  function ratingForPct(pct) {
    return round(RATING_MIN + (pct / 100) * (RATING_MAX - RATING_MIN));
  }

  /* Same mapping the server applies to the mean, so the marker can show where a
     rating lands before it is submitted. Duplicated deliberately: a preview is
     not worth a round trip on every pixel of drag. */
  function indexForRating(rating) {
    var fraction = (rating - RATING_MIN) / (RATING_MAX - RATING_MIN);
    return SCALE_MIN + fraction * (SCALE_MAX - SCALE_MIN);
  }

  /* --- Token ------------------------------------------------------------ */

  function readToken() {
    try {
      return window.localStorage.getItem(TOKEN_KEY);
    } catch (e) {
      return null; // private mode / storage blocked — voting degrades to none
    }
  }

  function ensureToken() {
    var existing = readToken();
    if (existing) return existing;
    var token;
    if (window.crypto && window.crypto.randomUUID) {
      token = window.crypto.randomUUID();
    } else {
      var bytes = new Uint8Array(16);
      window.crypto.getRandomValues(bytes);
      token = Array.prototype.map
        .call(bytes, function (b) { return ('0' + b.toString(16)).slice(-2); })
        .join('');
    }
    try {
      window.localStorage.setItem(TOKEN_KEY, token);
    } catch (e) {
      return null;
    }
    return token;
  }

  function clearToken() {
    try {
      window.localStorage.removeItem(TOKEN_KEY);
    } catch (e) { /* nothing to clear */ }
  }

  /* --- The drag bubble -------------------------------------------------- */

  var bubble = null;

  function showBubble(rating) {
    if (!bubble) {
      bubble = document.createElement('div');
      bubble.className = 'ppi-bubble';
      bubble.setAttribute('aria-hidden', 'true');
      track.appendChild(bubble);
    }
    /* Just the two numbers. The wording lives in the hint line below the track,
       which is already on screen — spelling it out here as well made a tooltip
       wide enough to cover the reading it is sitting on top of. */
    bubble.innerHTML = '';
    var strong = document.createElement('strong');
    strong.textContent = rating.toFixed(1);
    var mapped = document.createElement('span');
    mapped.className = 'ppi-bubble-mapped';
    mapped.textContent = indexForRating(rating).toFixed(1);
    bubble.appendChild(strong);
    bubble.appendChild(mapped);
    bubble.style.left = pctForRating(rating) + '%';
    bubble.hidden = false;
  }

  function hideBubble() {
    if (bubble) bubble.hidden = true;
  }

  /* --- Rendering -------------------------------------------------------- */

  /* Where the marker sits when nobody is dragging: the reader's pending answer
     if they have one, otherwise the published crowd figure, otherwise the
     midpoint — which means nothing and is styled to say so. */
  function restPointer() {
    if (draft !== null) {
      pointer.style.left = pctForRating(draft) + '%';
      return;
    }
    pointer.style.left = (crowdPct === null ? 50 : crowdPct) + '%';
    pointer.classList.toggle('is-empty', crowdPct === null);
  }

  function setDraft(rating) {
    draft = clamp(round(rating), RATING_MIN, RATING_MAX);
    pointer.style.left = pctForRating(draft) + '%';
    pointer.classList.remove('is-empty');
    pointer.classList.add('is-pending');
    pointer.setAttribute('aria-valuenow', draft.toFixed(1));
    pointer.setAttribute(
      'aria-valuetext',
      draft.toFixed(1) + ' of 10 — ' + wordFor(draft) +
      ', ' + indexForRating(draft).toFixed(1) + ' on the index scale'
    );
    showBubble(draft);
    updateAction();
  }

  function clearDraft() {
    draft = null;
    pointer.classList.remove('is-pending', 'is-dragging');
    hideBubble();
    restPointer();
    updateAction();
  }

  /* The button and the line above it are one message: what you can do next, and
     why you cannot do it yet. Keeping them in one function is what stops them
     drifting out of agreement. */
  function updateAction() {
    if (!available) {
      submitBtn.disabled = true;
      submitBtn.classList.remove('is-armed');
      submitLabel.textContent = 'Voting unavailable';
      hintText.textContent = 'Reader voting is offline right now — the model score above is unaffected.';
      hintEl.classList.remove('is-pending');
      withdrawBtn.hidden = true;
      pointer.setAttribute('aria-disabled', 'true');
      return;
    }

    pointer.removeAttribute('aria-disabled');
    withdrawBtn.hidden = myVote === null;

    if (sending) {
      submitBtn.disabled = true;
      submitLabel.textContent = 'Saving…';
      return;
    }

    /* Re-submitting the number already on record is a no-op, so the button is
       only live when the marker is somewhere new. */
    var isNew = draft !== null && draft !== myVote;
    submitBtn.disabled = !isNew;
    submitBtn.classList.toggle('is-armed', isNew);
    hintEl.classList.toggle('is-pending', isNew);

    if (isNew) {
      submitLabel.textContent = myVote === null ? 'Cast your read' : 'Update my read';
      hintText.textContent =
        'You picked ' + draft.toFixed(1) + ' of 10 — ' + wordFor(draft) +
        ' (' + indexForRating(draft).toFixed(1) + ' on the scale).';
    } else if (myVote !== null) {
      submitLabel.textContent = 'Update my read';
      hintText.textContent =
        'You voted ' + myVote.toFixed(1) + ' of 10 — ' + wordFor(myVote) +
        '. Drag the marker to change it.';
    } else {
      submitLabel.textContent = 'Cast your read';
      hintText.textContent = 'Drag the marker to where you think this week sits.';
    }
  }

  function request(method, body) {
    var headers = { 'Accept': 'application/json' };
    var token = method === 'GET' ? readToken() : ensureToken();
    if (token) headers['X-Voter-Token'] = token;
    if (body) headers['Content-Type'] = 'application/json';

    var seq = ++issued;
    return fetch(API, {
      method: method,
      headers: headers,
      body: body ? JSON.stringify(body) : undefined
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) throw new Error(data.error || 'Request failed.');
        data._seq = seq;
        return data;
      });
    });
  }

  function render(data) {
    if (data._seq && data._seq < rendered) return;
    rendered = data._seq || rendered;

    available = data.available !== false;
    myVote = typeof data.your_vote === 'number' ? data.your_vote : null;

    if (data.index === null || data.index === undefined) {
      crowdPct = null;
      valueEl.textContent = '—';
      levelEl.hidden = true;
      gapEl.hidden = true;
      fillEl.style.width = '0%';
      countEl.textContent = available
        ? (data.votes > 0
            ? data.votes + ' vote' + (data.votes === 1 ? '' : 's') + ' this week'
            : 'Be the first to vote this week')
        : 'Voting unavailable';
    } else {
      crowdPct = data.scale_pct;
      valueEl.textContent = data.index.toFixed(1);
      levelEl.hidden = false;
      levelEl.textContent = (data.level_label || '').toUpperCase();
      levelEl.className = 'status-badge status-' + (data.level_status || 'good');
      countEl.textContent =
        data.votes + ' vote' + (data.votes === 1 ? '' : 's') + ' this week';

      fillEl.style.width = data.scale_pct + '%';
      track.setAttribute('aria-valuenow', data.index.toFixed(1));

      var gap = data.index - modelScore;
      gapEl.hidden = false;
      gapEl.innerHTML = '';
      var gapValue = document.createElement('span');
      gapValue.className =
        'ppi-gap-value ' + (gap > 0 ? 'is-hotter' : 'is-cooler');
      gapValue.textContent = (gap > 0 ? '+' : '') + gap.toFixed(1);
      var gapLabel = document.createElement('span');
      gapLabel.className = 'ppi-gap-label';
      /* Must match the server-rendered wording in hormuz.html exactly, or the
         label visibly rewrites itself when this refresh lands. */
      gapLabel.textContent = 'vs model';
      gapEl.appendChild(gapValue);
      gapEl.appendChild(gapLabel);
    }

    /* A submitted vote is no longer a draft: drop it so the marker snaps back
       to the aggregate it just moved. A draft still being edited survives a
       background refresh — losing someone's half-made answer to a poll they
       did not trigger would be worse than showing a marker a few seconds old. */
    if (draft !== null && draft === myVote) clearDraft();
    else restPointer();

    updateAction();
  }

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
  }

  function track_(name, params) {
    if (typeof window.trackEvent === 'function') {
      window.trackEvent(name, params);
    } else if (typeof window.gtag === 'function') {
      window.gtag('event', name, Object.assign({ page_path: location.pathname }, params || {}));
    }
  }

  /* --- Dragging --------------------------------------------------------- */

  function ratingFromClientX(clientX) {
    var rect = track.getBoundingClientRect();
    if (!rect.width) return RATING_MIN;
    return ratingForPct(clamp((clientX - rect.left) / rect.width * 100, 0, 100));
  }

  var dragging = false;

  function onPointerDown(event) {
    if (!available || event.button > 0) return;
    dragging = true;
    pointer.classList.add('is-dragging');
    errorEl.hidden = true;
    /* Capture on the track, not the handle: the press that starts a drag often
       lands on the bar next to the handle, and a press anywhere on the scale is
       the most discoverable way to answer — nobody has to find the dot first. */
    try { track.setPointerCapture(event.pointerId); } catch (e) { /* older engines */ }
    setDraft(ratingFromClientX(event.clientX));
    event.preventDefault();
  }

  function onPointerMove(event) {
    if (!dragging) return;
    setDraft(ratingFromClientX(event.clientX));
    event.preventDefault();
  }

  function onPointerUp(event) {
    if (!dragging) return;
    dragging = false;
    pointer.classList.remove('is-dragging');
    try { track.releasePointerCapture(event.pointerId); } catch (e) { /* ditto */ }
    pointer.focus({ preventScroll: true });
  }

  track.addEventListener('pointerdown', onPointerDown);
  track.addEventListener('pointermove', onPointerMove);
  track.addEventListener('pointerup', onPointerUp);
  track.addEventListener('pointercancel', onPointerUp);

  /* Keyboard is a first-class way to cast a ballot here, not a fallback: the
     handle is a role="slider" and answers to the keys one carries. Steps are a
     tenth of a point, with a whole point on PageUp/PageDown.

     The step is taken from the value *snapped to tenths*, not from wherever a
     drag happened to leave the marker. A ballot dragged to 7.75 is announced as
     "7.8", so stepping the raw value to 7.85 announces "7.8" again and the key
     reads as broken to the one person who has no other cue that it worked. */
  pointer.addEventListener('keydown', function (event) {
    if (!available) return;
    var raw = draft !== null ? draft : (myVote !== null ? myVote : 5);
    var base = Math.round(raw * 10) / 10;
    var next = null;
    switch (event.key) {
      case 'ArrowRight': case 'ArrowUp':   next = base + 0.1; break;
      case 'ArrowLeft':  case 'ArrowDown': next = base - 0.1; break;
      case 'PageUp':     next = base + 1; break;
      case 'PageDown':   next = base - 1; break;
      case 'Home':       next = RATING_MIN; break;
      case 'End':        next = RATING_MAX; break;
      case 'Enter': case ' ':
        if (!submitBtn.disabled) { submitBtn.click(); event.preventDefault(); }
        return;
      default: return;
    }
    setDraft(next);
    event.preventDefault();
  });

  /* The bubble is a drag read-out, not a permanent label — it would otherwise
     sit over the trend chart above once the reader has moved on. */
  pointer.addEventListener('blur', function () {
    if (!dragging && draft !== null) hideBubble();
  });
  pointer.addEventListener('focus', function () {
    if (draft !== null) showBubble(draft);
  });

  /* --- Submitting ------------------------------------------------------- */

  submitBtn.addEventListener('click', function () {
    if (draft === null) return;
    errorEl.hidden = true;
    var value = draft;
    var isEdit = myVote !== null;
    var previousValue = myVote;
    sending = true;
    updateAction();
    request('POST', { value: value })
      .then(function (data) {
        myVote = value;
        render(data);
        clearDraft();
        track_('ppi_vote_submit', {
          rating_value: value,
          mapped_score: Math.round(indexForRating(value) * 10) / 10,
          sentiment_word: wordFor(value),
          is_edit: isEdit,
          previous_value: previousValue,
          report_slug: 'hormuz-index',
          page_path: location.pathname
        });
      })
      .catch(function (err) {
        showError(err.message);
      })
      .then(function () {
        sending = false;
        updateAction();
      });
  });

  withdrawBtn.addEventListener('click', function () {
    errorEl.hidden = true;
    sending = true;
    updateAction();
    request('DELETE')
      .then(function (data) {
        clearToken();
        data.your_vote = null;
        myVote = null;
        draft = null;
        render(data);
        clearDraft();
        track_('ppi_vote_withdraw', {
          report_slug: 'hormuz-index',
          page_path: location.pathname
        });
      })
      .catch(function (err) {
        showError(err.message);
      })
      .then(function () {
        sending = false;
        updateAction();
      });
  });

  /* The page is CDN-cached, so the server-rendered figures can be up to half an
     hour stale and never know about this browser's own vote. Refresh from the
     no-store endpoint on load. */
  updateAction();
  request('GET').then(render).catch(function () {
    available = false;
    updateAction();
  });
})();
