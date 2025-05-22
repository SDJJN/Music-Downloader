let selectedSongs = [];
let allFormats = [];
let currentUrl = "";

function showTab(tab) {
    document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
    if (tab === 'playlist') document.getElementById('playlistTab').style.display = '';
    if (tab === 'video') document.getElementById('videoTab').style.display = '';
    if (tab === 'ytmp3') document.getElementById('ytmp3Tab').style.display = '';
    if (tab === 'instagram') document.getElementById('instagramTab').style.display = '';
}

function searchPlaylist() {
  const name = document.getElementById('playlistName').value;
  fetch(`/search_playlist?name=${encodeURIComponent(name)}`)
    .then(res => res.json())
    .then(data => {
      const container = document.getElementById('songsList');
      container.innerHTML = '';
      data.songs.forEach(song => {
        container.innerHTML += `
          <div>
            <input type="checkbox" value="${song.videoId}" data-title="${song.title}">
            ${song.title}
          </div>
        `;
      });
    });
}

function addToDownloadCard() {
  const checkboxes = document.querySelectorAll('#songsList input[type=checkbox]:checked');
  checkboxes.forEach(cb => {
    const song = { id: cb.value, title: cb.dataset.title };
    if (!selectedSongs.some(s => s.id === song.id)) {
      selectedSongs.push(song);
    }
  });

  const card = document.getElementById('downloadCard');
  card.innerHTML = '';
  selectedSongs.forEach(song => {
    card.innerHTML += `<div>${song.title}</div>`;
  });
}

function downloadAll() {
  const quality = document.getElementById('quality').value;
  fetch('/download_all', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ songs: selectedSongs, quality })
  })
    .then(res => res.blob())
    .then(blob => {
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = 'songs.zip';
      link.click();
    });
}

function downloadVideo() {
  const url = document.getElementById('videoUrl').value;
  const quality = document.getElementById('videoQuality').value;
  fetch('/download_video', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, quality })
  })
    .then(res => res.blob())
    .then(blob => {
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = 'video.mp4';
      link.click();
    });
}

function downloadYtMp3() {
  const url = document.getElementById('ytmp3Url').value;
  const quality = document.getElementById('ytmp3Quality').value;
  fetch('/download_mp3', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, quality })
  })
    .then(res => {
      if (res.ok && res.headers.get('Content-Type').includes('audio')) {
        return res.blob();
      } else {
        return res.json().then(data => { throw new Error(data.error || "Download failed"); });
      }
    })
    .then(blob => {
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = 'audio.mp3';
      link.click();
    })
    .catch(err => alert(err.message));
}

function downloadInstagram() {
  const url = document.getElementById('instaUrl').value;
  const quality = document.getElementById('instaQuality').value;
  fetch('/download_instagram', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, quality })
  })
    .then(res => {
      if (res.ok && res.headers.get('Content-Type').includes('video')) {
        return res.blob();
      } else {
        return res.json().then(data => { throw new Error(data.error || "Download failed"); });
      }
    })
    .then(blob => {
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = 'instagram_video.mp4';
      link.click();
    })
    .catch(err => alert(err.message));
}

async function showVideoInfo() {
    const url = document.getElementById('videoUrl').value;
    if (!url) return alert('Please enter a YouTube URL.');
    currentUrl = url;

    // Show panel and loading state immediately
    const panel = document.getElementById('videoInfoPanel');
    panel.style.display = 'block';
    panel.innerHTML = `
      <div>
        <span style="font-weight:bold;" id="modalVideoTitle">Loading... Please wait a few seconds</span>
        <button onclick="closeVideoInfoPanel()" style="position:absolute;top:8px;right:12px;font-size:1.5em;background:none;border:none;cursor:pointer;color:#232946;">&times;</button>
        <div id="panelBody">
          <div style="padding:20px;">Loading formats...</div>
        </div>
      </div>
    `;

    try {
        const res = await fetch('/video_info', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url})
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        document.getElementById('modalVideoTitle').textContent = data.title;
        allFormats = data.formats;
        renderFormatTable(data, 'video');
    } catch (e) {
        document.getElementById('panelBody').innerHTML = `<div style="color:red;padding:20px;">Could not load video info.<br>${e.message}</div>`;
    }
}

function closeVideoInfoPanel() {
    document.getElementById('videoInfoPanel').style.display = 'none';
}

function renderFormatTable(data, tab) {
    // Buttons for toggling MP4/WebM
    let html = `
      <div style="margin:10px 0; text-align:center;">
        <img src="${data.thumbnail}" alt="Thumbnail" style="max-width:320px; margin-bottom:10px; border-radius:8px;"><br>
        <button id="btnMp4" onclick="renderFormatTable(allFormatsData, 'video')" style="margin:4px 8px; padding:6px 18px; border-radius:6px; border:1px solid #232946; background:${tab==='video'?'#232946':'#fff'}; color:${tab==='video'?'#fff':'#232946'}; font-weight:bold; cursor:pointer;">MP4</button>
        <button id="btnWebm" onclick="renderFormatTable(allFormatsData, 'webm')" style="margin:4px 8px; padding:6px 18px; border-radius:6px; border:1px solid #232946; background:${tab==='webm'?'#232946':'#fff'}; color:${tab==='webm'?'#fff':'#232946'}; font-weight:bold; cursor:pointer;">WebM</button>
      </div>
    `;

    // Save formats data globally for toggling
    window.allFormatsData = data;

    html += `
      <table style="width:100%; font-size:0.95em; border-collapse:collapse; border:2px solid #000;">
        <tr style="background:#e0e7ff;">
          <th style="border:1px solid #000;">Quality</th>
          <th style="border:1px solid #000;">Size</th>
          <th style="border:1px solid #000;">Audio</th>
          <th style="border:1px solid #000;">Download</th>
        </tr>`;

    const allowedRes = [
        '3840x2160', '2560x1440', '1920x1080', '1280x720', '854x480', '640x360',
        '2160p', '1440p', '1080p', '720p', '480p', '360p'
    ];
    let filtered = [];
    if (tab === 'video') {
        filtered = allFormats.filter(f =>
            f.ext === 'mp4' &&
            f.vcodec !== 'none' &&
            allowedRes.includes(f.resolution) &&
            f.filesize_mb && f.filesize_mb > 0 // Only keep formats with size info > 0
        );
    } else {
        filtered = allFormats.filter(f =>
            f.ext === 'webm' &&
            f.vcodec !== 'none' &&
            allowedRes.includes(f.resolution) &&
            f.filesize_mb && f.filesize_mb > 0 // Only keep formats with size info > 0
        );
    }

    // Sort by resolution descending (highest quality first)
    filtered.sort((a, b) => {
        const getHeight = res => {
            if (!res) return 0;
            if (res.endsWith('p')) return parseInt(res);
            if (res.includes('x')) return parseInt(res.split('x')[1]);
            return 0;
        };
        return getHeight(b.resolution) - getHeight(a.resolution);
    });

    for (const f of filtered) {
        let audioWarn = '';
        let formatString = f.format_id;
        let mergeFormat = f.ext;
        if (f.acodec === 'none') {
            audioWarn = '<span style="color:red;">Video-only: will be merged with best audio (may not be perfect)</span>';
            if (f.ext === 'webm') {
                formatString = `${f.format_id}+bestaudio[ext=webm][abr=320]/bestaudio[abr=320]/bestaudio`;
                mergeFormat = 'webm';
            } else {
                formatString = `${f.format_id}+bestaudio[ext=mp4][abr=320]/bestaudio[abr=320]/bestaudio`;
                mergeFormat = 'mp4';
            }
        }
        html += `<tr>
            <td style="border:1px solid #000;">${f.resolution || '-'}</td>
            <td style="border:1px solid #000;">${f.filesize_mb} MB</td>
            <td style="border:1px solid #000;">${f.acodec !== 'none' ? 'Yes' : 'No'} ${audioWarn}</td>
            <td style="border:1px solid #000;">
                <button onclick="downloadSelectedFormat('${currentUrl}', '${f.format_id}${f.acodec==='none'?'+bestaudio[ext='+f.ext+']':''}', '${f.ext}')">Download</button>
            </td>
        </tr>`;
    }
    html += '</table>';
    document.getElementById('panelBody').innerHTML = html;
}

function downloadSelectedFormat(url, formatString, mergeFormat) {
    fetch('/download_selected_format', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, formatString, mergeFormat })
    })
    .then(async res => {
        if (res.ok) {
            return res.blob();
        } else {
            // Try to parse error from API
            let data;
            try {
                data = await res.json();
            } catch {
                throw new Error("Server error or invalid response");
            }
            throw new Error(data.error || "Download failed");
        }
    })
    .then(blob => {
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `video.${mergeFormat}`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    })
    .catch(err => {
        alert("Download failed: " + err.message);
    });
}





