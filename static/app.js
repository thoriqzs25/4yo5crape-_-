/* ============================================
   AYO Slots Utopia — Frontend App
   ============================================ */

// Set default dates to today
const startDateInput = document.getElementById('start_date');
const endDateInput = document.getElementById('end_date');
if (startDateInput) startDateInput.valueAsDate = new Date();
if (endDateInput) endDateInput.valueAsDate = new Date();

// Rate limiting state
let cooldownInterval = null;
let cooldownEndTime = null;

// City autocomplete
let autocompleteTimeout;
const lokasiInput = document.getElementById('lokasi');
const citySuggestions = document.getElementById('citySuggestions');
const selectedCitiesContainer = document.getElementById('selectedCitiesContainer');
let selectedCities = [];

let currentEventSource = null;
let lastScrapedData = null;

/* ---------- Helpers ---------- */

function debounce(func, delay) {
  return function (...args) {
    clearTimeout(autocompleteTimeout);
    autocompleteTimeout = setTimeout(() => func.apply(this, args), delay);
  };
}

function showToast(message) {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  document.body.appendChild(toast);

  requestAnimationFrame(() => toast.classList.add('show'));
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 300);
  }, 2200);
}

function colorizeLogLine(line) {
  const lower = line.toLowerCase();
  if (lower.includes('error') || lower.includes('fail')) return `<span class="log-error">${escapeHtml(line)}</span>`;
  if (lower.includes('warn')) return `<span class="log-warn">${escapeHtml(line)}</span>`;
  if (lower.includes('success') || lower.includes('done') || lower.includes('complete')) return `<span class="log-success">${escapeHtml(line)}</span>`;
  if (lower.includes('info') || lower.includes('fetch')) return `<span class="log-info">${escapeHtml(line)}</span>`;
  return escapeHtml(line);
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/* ---------- Results Rendering ---------- */

function renderResults(data) {
  const output = document.getElementById('output');
  if (!output) return;

  if (!Array.isArray(data) || data.length === 0) {
    output.innerHTML = `
      <div class="empty-state">
        <span class="empty-state-icon">🎾</span>
        <h3>No venues found</h3>
        <p>Try adjusting your filters or dates.</p>
      </div>`;
    return;
  }

  let html = '';
  data.forEach((venue, idx) => {
    const platform = venue.platform || 'ayo';
    const sportId = venue.sport_id || venue.cabor || '7';
    const sportName = sportId == 12 ? 'padel' : sportId == 15 ? 'pickleball' : 'tennis';
    const badgeClass = sportName === 'padel' ? 'badge-padel' : sportName === 'pickleball' ? 'badge-pickleball' : 'badge-tennis';
    const emoji = sportName === 'padel' ? '🏓' : sportName === 'pickleball' ? '🥒' : '🎾';

    html += `<div class="venue-card" style="animation-delay:${(idx * 0.05).toFixed(2)}s">`;
    html += `<div class="venue-header">`;
    html += `<a href="${escapeHtml(venue.url || '#')}" target="_blank" rel="noopener" class="venue-name">`;
    html += `${escapeHtml(venue.name || 'Unknown Venue')} <span class="external">↗</span></a>`;
    html += `<div class="venue-badges">`;
    html += `<span class="badge ${badgeClass}">${emoji} ${sportName}</span>`;
    if (venue.location) html += `<span class="badge badge-location">📍 ${escapeHtml(venue.location)}</span>`;
    html += `</div></div>`;

    // Fields & slots
    const fields = venue.available_fields || [];
    if (fields.length === 0 && Array.isArray(venue.time_slots) && venue.time_slots.length) {
      // Flat structure — group by field_name
      const byField = {};
      venue.time_slots.forEach(slot => {
        const fname = slot.field_name || 'Court';
        if (!byField[fname]) byField[fname] = [];
        byField[fname].push(slot);
      });
      Object.entries(byField).forEach(([fname, slots]) => {
        html += renderFieldSlots(fname, slots);
      });
    } else {
      fields.forEach(field => {
        html += renderFieldSlots(field.field_name || 'Court', field.time_slots || []);
      });
    }

    html += `</div>`;
  });

  output.innerHTML = html;
}

function renderFieldSlots(fieldName, slots) {
  if (!slots.length) return '';
  let html = `<div class="venue-fields">`;
  html += `<div class="field-name">${escapeHtml(fieldName)}</div>`;
  html += `<div class="slots-grid">`;
  slots.forEach(slot => {
    const available = slot.is_available !== 0 && slot.is_available !== false;
    const time = `${(slot.start_time || '').substring(0,5)}-${(slot.end_time || '').substring(0,5)}`;
    const price = slot.price ? `Rp ${Number(slot.price).toLocaleString()}` : '—';
    html += `<div class="slot-chip ${available ? '' : 'unavailable'}">`;
    html += `<span class="slot-time">${time}</span>`;
    html += `<span class="slot-price">${price}</span>`;
    html += `</div>`;
  });
  html += `</div></div>`;
  return html;
}

/* ---------- Settings / URL ---------- */

function loadSettingsFromURL() {
  const params = new URLSearchParams(window.location.search);

  if (params.has('platform')) document.getElementById('platform').value = params.get('platform');
  if (params.has('start_date')) document.getElementById('start_date').value = params.get('start_date');
  if (params.has('end_date')) document.getElementById('end_date').value = params.get('end_date');
  if (params.has('cabor')) document.getElementById('cabor').value = params.get('cabor');
  if (params.has('start_time')) document.getElementById('start_time').value = params.get('start_time');
  if (params.has('end_time')) document.getElementById('end_time').value = params.get('end_time');
  if (params.has('sortby')) document.getElementById('sortby').value = params.get('sortby');
  if (params.has('cheapest_first')) document.getElementById('cheapest_first').checked = params.get('cheapest_first') === 'true';

  if (params.has('lokasi') && params.get('lokasi')) {
    const cities = params.get('lokasi').split(',');
    cities.forEach(cityValue => {
      const cityName = cityValue.replace(/\+/g, ' ');
      selectedCities.push({ name: cityName, value: cityValue });
    });
  } else {
    selectedCities.push({ name: 'Kota Jakarta Selatan', value: 'Kota+Jakarta+Selatan' });
    selectedCities.push({ name: 'Kota Jakarta Timur', value: 'Kota+Jakarta+Timur' });
  }
  renderSelectedCities();
}

function updateURLParams(data) {
  const params = new URLSearchParams();
  if (data.platform) params.set('platform', data.platform);
  if (data.lokasi) params.set('lokasi', data.lokasi);
  if (data.cabor) params.set('cabor', data.cabor);
  if (data.start_date) params.set('start_date', data.start_date);
  if (data.end_date) params.set('end_date', data.end_date);
  if (data.start_time) params.set('start_time', data.start_time);
  if (data.end_time) params.set('end_time', data.end_time);
  if (data.sortby) params.set('sortby', data.sortby);
  if (data.cheapest_first) params.set('cheapest_first', 'true');

  window.history.replaceState({}, '', window.location.pathname + '?' + params.toString());
}

/* ---------- Platform & Sport ---------- */

function updateSportDropdown() {
  const platform = document.getElementById('platform').value;
  const cabor = document.getElementById('cabor');
  if (platform === 'gelora' || platform === 'all') {
    cabor.value = '7';
    cabor.disabled = true;
  } else {
    cabor.disabled = false;
  }
}

document.getElementById('platform')?.addEventListener('change', updateSportDropdown);

/* ---------- Rate Limit ---------- */

async function checkRateLimit() {
  try {
    const response = await fetch('/scrape/check-limit');
    const data = await response.json();
    if (!data.allowed && data.seconds_remaining > 0) startCooldown(data.seconds_remaining);
  } catch (error) {
    console.error('Error checking rate limit:', error);
  }
}

function startCooldown(seconds) {
  const submitBtn = document.getElementById('submitBtn');
  const cooldownIndicator = document.getElementById('cooldownIndicator');
  cooldownEndTime = Date.now() + (seconds * 1000);

  if (cooldownInterval) clearInterval(cooldownInterval);
  cooldownIndicator.classList.add('active');
  updateCooldownButton();
  cooldownInterval = setInterval(updateCooldownButton, 1000);
}

function updateCooldownButton() {
  const submitBtn = document.getElementById('submitBtn');
  const cooldownIndicator = document.getElementById('cooldownIndicator');
  const cooldownSeconds = document.getElementById('cooldownSeconds');
  const remainingMs = cooldownEndTime - Date.now();

  if (remainingMs <= 0) {
    clearInterval(cooldownInterval);
    cooldownInterval = null;
    cooldownEndTime = null;
    submitBtn.disabled = false;
    submitBtn.innerHTML = 'Start Scraping';
    cooldownIndicator.classList.remove('active');
  } else {
    const remainingSeconds = Math.ceil(remainingMs / 1000);
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span class="spinner-inline"></span> Wait ${remainingSeconds}s`;
    cooldownSeconds.textContent = remainingSeconds;
  }
}

checkRateLimit();

/* ---------- City Autocomplete ---------- */

function addCity(cityName, cityValue) {
  if (!selectedCities.find(c => c.value === cityValue)) {
    selectedCities.push({ name: cityName, value: cityValue });
    renderSelectedCities();
  }
  lokasiInput.value = '';
}

function removeCity(cityValue) {
  selectedCities = selectedCities.filter(c => c.value !== cityValue);
  renderSelectedCities();
}

function renderSelectedCities() {
  selectedCitiesContainer.innerHTML = '';
  selectedCities.forEach(city => {
    const chip = document.createElement('div');
    chip.className = 'city-chip';
    chip.innerHTML = `<span>${escapeHtml(city.name)}</span><span class="city-chip-remove" data-value="${city.value}">&times;</span>`;
    selectedCitiesContainer.appendChild(chip);
  });

  selectedCitiesContainer.querySelectorAll('.city-chip-remove').forEach(btn => {
    btn.addEventListener('click', function () {
      removeCity(this.getAttribute('data-value'));
    });
  });
}

async function fetchCitySuggestions(term) {
  if (!term || term.length < 2) {
    citySuggestions.innerHTML = '';
    citySuggestions.classList.remove('active');
    return;
  }
  try {
    const response = await fetch(`/autocity?term=${encodeURIComponent(term)}`);
    const cities = await response.json();
    if (cities.length > 0) {
      citySuggestions.innerHTML = cities.map(city =>
        `<div class="autocomplete-item" data-value="${escapeHtml(city.value)}">${escapeHtml(city.value)}</div>`
      ).join('');
      citySuggestions.classList.add('active');
      citySuggestions.querySelectorAll('.autocomplete-item').forEach(item => {
        item.addEventListener('click', function () {
          const value = this.getAttribute('data-value');
          const cityName = value;
          const cityValue = value.replace(/ /g, '+');
          addCity(cityName, cityValue);
          citySuggestions.innerHTML = '';
          citySuggestions.classList.remove('active');
        });
      });
    } else {
      citySuggestions.innerHTML = '';
      citySuggestions.classList.remove('active');
    }
  } catch (error) {
    console.error('Error fetching city suggestions:', error);
    citySuggestions.innerHTML = '';
    citySuggestions.classList.remove('active');
  }
}

lokasiInput?.addEventListener('input', debounce(function (e) {
  fetchCitySuggestions(e.target.value);
}, 500));

document.addEventListener('click', function (e) {
  if (!e.target.closest('.autocomplete-container')) {
    citySuggestions.innerHTML = '';
    citySuggestions.classList.remove('active');
  }
});

lokasiInput?.addEventListener('keydown', function (e) {
  const items = citySuggestions.querySelectorAll('.autocomplete-item');
  const activeItem = citySuggestions.querySelector('.autocomplete-item.active');
  let index = Array.from(items).indexOf(activeItem);

  if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (activeItem) activeItem.classList.remove('active');
    index = (index + 1) % items.length;
    if (items[index]) items[index].classList.add('active');
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (activeItem) activeItem.classList.remove('active');
    index = (index - 1 + items.length) % items.length;
    if (items[index]) items[index].classList.add('active');
  } else if (e.key === 'Enter' && activeItem) {
    e.preventDefault();
    activeItem.click();
  } else if (e.key === 'Escape') {
    citySuggestions.innerHTML = '';
    citySuggestions.classList.remove('active');
  }
});

/* ---------- Form Submission ---------- */

document.getElementById('scraperForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();

  const form = e.target;
  const formData = new FormData(form);
  const lokasiValue = selectedCities.length > 0 ? selectedCities.map(c => c.value).join(',') : '';

  const data = {
    platform: formData.get('platform'),
    lokasi: lokasiValue,
    cabor: formData.get('cabor'),
    start_date: formData.get('start_date'),
    end_date: formData.get('end_date'),
    start_time: formData.get('start_time'),
    end_time: formData.get('end_time'),
    sortby: formData.get('sortby'),
    max_pages: '0',
    max_venues: '0',
    cheapest_first: document.getElementById('cheapest_first').checked
  };

  updateURLParams(data);

  if (currentEventSource) currentEventSource.close();

  // Reset UI
  document.getElementById('loading').classList.add('active');
  document.getElementById('logsOutput').classList.remove('active');
  document.getElementById('results').classList.remove('active');
  document.getElementById('error').classList.remove('active');

  const selectedPlatform = data.platform || 'ayo';
  document.getElementById('progressBarAyo').style.width = '0%';
  document.getElementById('progressTextAyo').textContent = '0%';
  document.getElementById('progressBarGelora').style.width = '0%';
  document.getElementById('progressTextGelora').textContent = '0%';
  document.getElementById('progressContainerAyo').classList.toggle('active', selectedPlatform === 'ayo' || selectedPlatform === 'all');
  document.getElementById('progressContainerGelora').classList.toggle('active', selectedPlatform === 'gelora' || selectedPlatform === 'all');

  const submitBtn = document.getElementById('submitBtn');
  submitBtn.disabled = true;
  submitBtn.innerHTML = '<span class="spinner-inline"></span> Starting…';

  document.getElementById('logsOutput').innerHTML = '';
  document.getElementById('output').textContent = '';

  try {
    const response = await fetch('/scrape', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });

    const result = await response.json();

    if (response.status === 429 || result.rate_limited) throw new Error(result.error);
    if (!result.success) throw new Error(result.error);

    const sessionId = result.session_id;

    document.getElementById('loading').classList.remove('active');
    document.getElementById('logsOutput').classList.add('active');

    currentEventSource = new EventSource(`/scrape/progress/${sessionId}`);

    currentEventSource.onmessage = function (event) {
      const data = JSON.parse(event.data);
      if (data.message) {
        const logsOutput = document.getElementById('logsOutput');
        const line = document.createElement('div');
        line.className = 'log-line';
        line.innerHTML = colorizeLogLine(data.message);
        logsOutput.appendChild(line);
        logsOutput.scrollTop = logsOutput.scrollHeight;
      }
    };

    currentEventSource.addEventListener('progress', function (event) {
      const data = JSON.parse(event.data);
      const plat = data.platform || 'ayo';
      const suffix = plat === 'gelora' ? 'Gelora' : 'Ayo';
      document.getElementById('progressContainer' + suffix).classList.add('active');
      document.getElementById('progressBar' + suffix).style.width = data.percent + '%';
      document.getElementById('progressText' + suffix).textContent = `${data.current}/${data.total} (${data.percent}%)`;
    });

    currentEventSource.addEventListener('complete', async function (event) {
      currentEventSource.close();
      currentEventSource = null;

      try {
        const resultResponse = await fetch(`/scrape/result/${sessionId}`);
        const finalResult = await resultResponse.json();

        if (finalResult.success) {
          lastScrapedData = finalResult.data;

          // Render structured cards from JSON data
          renderResults(lastScrapedData);

          // Also keep raw text as hidden fallback or behind a toggle if needed
          // For now we render cards; if cards are empty we fall back
          if (!lastScrapedData || lastScrapedData.length === 0) {
            document.getElementById('output').textContent = finalResult.output || 'No results.';
          }

          const count = Array.isArray(finalResult.data) ? finalResult.data.length : 0;
          document.getElementById('venueCount').innerHTML = `${count} <span class="venue-count">venues</span>`;
          document.getElementById('results').classList.add('active');
        } else {
          throw new Error(finalResult.error);
        }
      } catch (error) {
        document.getElementById('error').textContent = 'Error fetching results: ' + error.message;
        document.getElementById('error').classList.add('active');
      }

      startCooldown(120);
    });

    currentEventSource.addEventListener('error', function (event) {
      if (event.data) {
        const data = JSON.parse(event.data);
        document.getElementById('error').textContent = 'Error: ' + data.error;
      } else {
        document.getElementById('error').textContent = 'Connection error occurred';
      }
      document.getElementById('error').classList.add('active');
      currentEventSource.close();
      currentEventSource = null;
      checkRateLimit();
    });

  } catch (error) {
    document.getElementById('error').textContent = 'Error: ' + error.message;
    document.getElementById('error').classList.add('active');
    document.getElementById('loading').classList.remove('active');
    submitBtn.disabled = false;
    submitBtn.innerHTML = 'Start Scraping';
    checkRateLimit();
  }
});

/* ---------- Actions ---------- */

document.getElementById('copyBtn')?.addEventListener('click', async (e) => {
  e.preventDefault();
  const outputText = document.getElementById('output').textContent;

  if (!outputText) {
    showToast('No results to copy!');
    return;
  }

  try {
    await navigator.clipboard.writeText(outputText);
    showToast('Copied to clipboard!');
  } catch (err) {
    const textarea = document.createElement('textarea');
    textarea.value = outputText;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand('copy');
      showToast('Copied to clipboard!');
    } catch {
      showToast('Failed to copy. Please select and copy manually.');
    }
    document.body.removeChild(textarea);
  }
});

document.getElementById('downloadTxt')?.addEventListener('click', (e) => {
  e.preventDefault();
  window.location.href = '/download/txt';
});

/* ---------- WA Poll ---------- */

function findConsecutiveSlots(venuesData) {
  const results = [];
  for (const venue of venuesData) {
    const platform = venue.platform || 'ayo';
    const fieldDateSlots = {};

    if (venue.available_fields) {
      for (const field of venue.available_fields) {
        for (const slot of (field.time_slots || [])) {
          const key = `${field.field_name}|||${slot.date || ''}`;
          if (!fieldDateSlots[key]) fieldDateSlots[key] = { field_name: field.field_name, date: slot.date || '', slots: [] };
          fieldDateSlots[key].slots.push(slot);
        }
      }
    } else if (venue.time_slots && venue.time_slots.length && typeof venue.time_slots[0] === 'object') {
      for (const slot of venue.time_slots) {
        const fname = slot.field_name || 'Unknown';
        const key = `${fname}|||${slot.date || ''}`;
        if (!fieldDateSlots[key]) fieldDateSlots[key] = { field_name: fname, date: slot.date || '', slots: [] };
        fieldDateSlots[key].slots.push(slot);
      }
    }

    for (const entry of Object.values(fieldDateSlots)) {
      const norm = t => (t || '').substring(0, 5);
      const slots = entry.slots.sort((a, b) => norm(a.start_time).localeCompare(norm(b.start_time)));
      let group = [slots[0]];
      for (let i = 1; i < slots.length; i++) {
        if (norm(slots[i].start_time) === norm(slots[i - 1].end_time)) {
          group.push(slots[i]);
        } else {
          if (group.length >= 2) {
            results.push({
              venue_name: venue.name,
              venue_url: venue.url,
              field_name: entry.field_name,
              platform: platform,
              date: entry.date,
              start_time: norm(group[0].start_time),
              end_time: norm(group[group.length - 1].end_time),
              hours: group.length,
              total_price: group.reduce((sum, s) => sum + (parseInt(s.price) || 0), 0)
            });
          }
          group = [slots[i]];
        }
      }
      if (group.length >= 2) {
        results.push({
          venue_name: venue.name,
          venue_url: venue.url,
          field_name: entry.field_name,
          platform: platform,
          date: entry.date,
          start_time: norm(group[0].start_time),
          end_time: norm(group[group.length - 1].end_time),
          hours: group.length,
          total_price: group.reduce((sum, s) => sum + (parseInt(s.price) || 0), 0)
        });
      }
    }
  }
  results.sort((a, b) => (a.total_price || Infinity) - (b.total_price || Infinity));
  return results;
}

document.getElementById('whatsappBtn')?.addEventListener('click', (e) => {
  e.preventDefault();
  if (!lastScrapedData || lastScrapedData.length === 0) {
    showToast('Run a scrape first!');
    return;
  }
  const consecutive = findConsecutiveSlots(lastScrapedData);
  if (consecutive.length === 0) {
    showToast('No fields with 2+ consecutive hours found.');
    return;
  }

  function fmtDate(dateStr) {
    try {
      const dt = new Date(dateStr + 'T00:00:00');
      return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch { return dateStr; }
  }
  function fmtPrice(price) {
    if (!price || price <= 0) return '';
    if (price % 1000 === 0) return `Rp ${price / 1000}k`;
    return `Rp ${price.toLocaleString()}`;
  }

  let msg = `Tennis Court Poll\n\nWhich slot works for you?\n\n`;
  consecutive.forEach((item, i) => {
    const priceStr = item.total_price > 0 ? ` | ${fmtPrice(item.total_price)} for ${item.hours}h` : '';
    msg += `${i + 1}. ${item.venue_name} - ${item.field_name}\n`;
    msg += `   ${fmtDate(item.date)} ${item.start_time}-${item.end_time}${priceStr}\n`;
    msg += `   ${item.venue_url}\n\n`;
  });
  msg += `Reply with your number!`;
  window.open(`https://wa.me/?text=${encodeURIComponent(msg)}`, '_blank');
});

/* ---------- Init ---------- */

loadSettingsFromURL();
updateSportDropdown();
