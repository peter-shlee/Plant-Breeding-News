(() => {
  const source = document.getElementById("markdown-source");
  if (!source) return;

  const pageUrl = document.body.dataset.pageUrl || window.location.pathname;
  const baseUrl = document.body.dataset.baseurl || "";

  const escapeHtml = (value) =>
    String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");

  const escapeAttr = escapeHtml;

  const text = (node) => (node ? node.textContent.replace(/\s+/g, " ").trim() : "");

  const sourceLabels = {
    nics: "NICS",
    nihhs: "NIHHS",
    rda: "RDA",
    sciencedaily: "ScienceDaily",
    seedworld: "Seed World",
    news: "News",
  };

  const sourceDisplayName = (sourceName) => {
    if (sourceName === "전체") return "전체";
    const key = String(sourceName || "news").toLowerCase();
    return sourceLabels[key] || String(sourceName || "news").toUpperCase();
  };

  const filterButtonMarkup = (values) =>
    values
      .map(
        (value, index) =>
          `<button type="button" class="${index === 0 ? "is-active" : ""}" data-source="${escapeAttr(value)}">${escapeHtml(sourceDisplayName(value))}</button>`,
      )
      .join("");

  const findHeading = (level, needle) =>
    Array.from(source.querySelectorAll(level)).find((heading) => text(heading).includes(needle));

  const siblingsUntilNextH2 = (heading) => {
    const nodes = [];
    for (let node = heading?.nextElementSibling; node; node = node.nextElementSibling) {
      if (node.tagName === "H2") break;
      nodes.push(node);
    }
    return nodes;
  };

  const normalizeHref = (href) => {
    const rawHref = String(href || "").trim();
    if (!rawHref) return "#";
    if (/^(mailto:|tel:|#)/i.test(rawHref)) return rawHref;
    if (/^https?:/i.test(rawHref)) {
      try {
        const url = new URL(rawHref);
        url.pathname = url.pathname.replace(/\.md$/i, ".html");
        return url.href;
      } catch {
        return "#";
      }
    }
    if (/^[a-z][a-z0-9+.-]*:/i.test(rawHref)) return "#";
    const hashIndex = rawHref.indexOf("#");
    const queryIndex = rawHref.indexOf("?");
    const splitIndex = [hashIndex, queryIndex].filter((index) => index >= 0).sort((a, b) => a - b)[0];
    const path = splitIndex >= 0 ? rawHref.slice(0, splitIndex) : rawHref;
    const suffix = splitIndex >= 0 ? rawHref.slice(splitIndex) : "";
    return `${path.replace(/\.md$/i, ".html")}${suffix}`;
  };

  const parseItemsFromHeading = (headingLabel, limit = Infinity) => {
    const heading = findHeading("h2", headingLabel);
    if (!heading) return [];

    const listItems = [];
    siblingsUntilNextH2(heading).forEach((node) => {
      if (node.tagName !== "UL") return;
      Array.from(node.children).forEach((li) => {
        if (li.tagName === "LI") listItems.push(li);
      });
    });

    return listItems
      .map((li) => {
        const titleLink = li.querySelector("strong a") || li.querySelector("a");
        if (!titleLink) return null;
        const nested = Array.from(li.querySelectorAll(":scope > ul > li")).map(text);
        const allLinks = Array.from(li.querySelectorAll("a"));
        const originalLink = allLinks.find((link) => text(link).includes("원문"));
        const sourceCode = li.querySelector("code");
        const meta = nested[0] || "";
        const date = (meta.match(/\d{4}-\d{2}-\d{2}/) || [])[0] || "";
        const excerpt = nested.find((line) => line && !line.includes("읽기") && !line.includes("원문")) || "";
        return {
          title: text(titleLink),
          href: normalizeHref(titleLink.getAttribute("href")),
          originalHref: normalizeHref(originalLink?.getAttribute("href")),
          source: text(sourceCode) || "news",
          date,
          excerpt,
        };
      })
      .filter(Boolean)
      .slice(0, limit);
  };

  const parseLinkListFromHeading = (headingLabel, limit = Infinity) => {
    const heading = findHeading("h2", headingLabel);
    if (!heading) return [];
    const items = [];
    siblingsUntilNextH2(heading).forEach((node) => {
      if (node.tagName !== "UL") return;
      Array.from(node.querySelectorAll("li a")).forEach((link) => {
        items.push({ title: text(link), href: normalizeHref(link.getAttribute("href")) });
      });
    });
    return items.slice(0, limit);
  };

  const parseArchive = (limit = Infinity) => parseLinkListFromHeading("지난 주간 아카이브", limit);

  const parseSources = () => parseLinkListFromHeading("출처별 모아보기");

  const setActiveNav = () => {
    const normalizedPath = (pageUrl || window.location.pathname).replace(/\/index\.html$/, "/");
    const normalizedBasePath = baseUrl ? `${baseUrl.replace(/\/$/, "")}/` : "/";
    const isHomePath = normalizedPath === "/" || normalizedPath === normalizedBasePath;
    const hash = window.location.hash;
    document.querySelectorAll(".pbn-nav a").forEach((link) => {
      const href = link.getAttribute("href") || "";
      const url = new URL(href, window.location.href);
      const targetPath = url.pathname.replace(/\/index\.html$/, "/");
      const isActive =
        (targetPath.endsWith("/podcast/") && normalizedPath.includes("/podcast/")) ||
        (targetPath.includes("/weekly/") && normalizedPath.includes("/weekly/")) ||
        (url.hash === "#news-feed" && isHomePath && (!hash || hash === "#news-feed")) ||
        (url.hash === "#briefing" && isHomePath && hash === "#briefing") ||
        (url.hash === "#weekly-archive" && isHomePath && hash === "#weekly-archive");
      link.classList.toggle("is-active", isActive);
      if (isActive) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  };

  const scrollToCurrentHash = () => {
    let id = window.location.hash.slice(1);
    try {
      id = decodeURIComponent(id);
    } catch {
      // Keep malformed hashes from interrupting the transformed page boot.
    }
    if (!id) return;
    const alignToTarget = () => {
      const target = document.getElementById(id);
      if (!target) return;
      const top = Math.max(0, target.getBoundingClientRect().top + window.scrollY - 96);
      window.scrollTo({ top, behavior: "auto" });
    };
    requestAnimationFrame(alignToTarget);
    setTimeout(alignToTarget, 50);
    setTimeout(alignToTarget, 250);
    setTimeout(alignToTarget, 750);
  };

  const escapeSelectorValue = (value) =>
    window.CSS?.escape ? CSS.escape(value) : String(value).replace(/["\\]/g, "\\$&");

  const deactivateSourceAnchors = () => {
    source.querySelectorAll("[id]").forEach((element) => element.removeAttribute("id"));
  };

  const parseBriefing = () => {
    const heading = findHeading("h2", "30초");
    if (!heading) {
      return [
        { title: "핵심 변화", body: "이번 주 식물 육종과 종자 산업에서 신호가 강한 흐름을 선별했습니다." },
        { title: "기술 신호", body: "유전체, 기후 회복력, 품종 개발 관련 뉴스를 우선 큐레이션합니다." },
        { title: "시장 맥락", body: "현장과 정책 변화를 함께 들어볼 수 있도록 짧은 오디오로 정리합니다." },
      ];
    }

    const cards = [];
    let current = null;
    siblingsUntilNextH2(heading).forEach((node) => {
      if (node.tagName === "H3") {
        current = { title: text(node).replace(/^\d+\)\s*/, ""), body: "" };
        cards.push(current);
        return;
      }
      if (!current || node.tagName !== "UL") return;
      const first = node.querySelector("li");
      if (first) current.body = text(first).replace(/\s*\(?원문\)?\s*$/, "");
    });
    return cards.filter((card) => card.title && card.body).slice(0, 3);
  };

  const metadataFromHome = () => {
    const nodes = Array.from(source.querySelectorAll("li, p")).map(text);
    const updatedText = nodes.find((line) => line.includes("마지막 업데이트")) || "";
    const coverageText = nodes.find((line) => line.includes("커버리지")) || "";
    const updated = (updatedText.match(/20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}\s*\(?KST\)?/) || [])[0];
    const coverage = (coverageText.match(/20\d{2}-\d{2}-\d{2}\s*~\s*20\d{2}-\d{2}-\d{2}/) || [])[0];
    return {
      updated: updated || "2026-05-22 22:15 (KST)",
      coverage: coverage || "2026-05-15 ~ 2026-05-22",
    };
  };

  const fetchPodcast = async () => {
    try {
      const response = await fetch(`${baseUrl}/podcast/latest.json`, { cache: "no-store" });
      if (!response.ok) return null;
      return await response.json();
    } catch {
      return null;
    }
  };

  const waveform = (count = 46) =>
    Array.from({ length: count }, (_, index) => {
      const height = 12 + Math.round(Math.abs(Math.sin(index * 0.72)) * 34) + (index % 5) * 3;
      return `<span style="--h:${height}px;--i:${index}"></span>`;
    }).join("");

  const formatTime = (seconds) => {
    if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.floor(seconds % 60);
    return `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
  };

  const PLAYER_STORAGE_KEY = "pbn-player-state-v1";
  const TRANSCRIPT_HIGHLIGHT_TOLERANCE_SECONDS = 0.75;
  let sharedAudio;
  let sharedAudioSrc = "";
  let pendingSeekTime = null;
  let playerBindings = [];

  const absoluteAudioSrc = (src) => {
    const rawSrc = String(src || "").trim();
    if (!rawSrc) return "";
    try {
      return new URL(rawSrc, window.location.href).href;
    } catch {
      return rawSrc;
    }
  };

  const readStoredPlayerState = () => {
    try {
      return JSON.parse(window.sessionStorage.getItem(PLAYER_STORAGE_KEY) || "null");
    } catch {
      return null;
    }
  };

  const writeStoredPlayerState = () => {
    if (!sharedAudio || !sharedAudioSrc) return;
    try {
      window.sessionStorage.setItem(
        PLAYER_STORAGE_KEY,
        JSON.stringify({
          src: sharedAudioSrc,
          currentTime: sharedAudio.currentTime || 0,
          paused: sharedAudio.paused,
        }),
      );
    } catch {
      // Session persistence is only a convenience; playback must keep working without it.
    }
  };

  const getSharedAudio = () => {
    if (sharedAudio) return sharedAudio;
    sharedAudio = new Audio();
    sharedAudio.preload = "metadata";
    sharedAudio.addEventListener("play", () => {
      updateAllPlayers();
      writeStoredPlayerState();
    });
    sharedAudio.addEventListener("pause", () => {
      updateAllPlayers();
      writeStoredPlayerState();
    });
    sharedAudio.addEventListener("loadedmetadata", updateAllPlayers);
    sharedAudio.addEventListener("durationchange", updateAllPlayers);
    sharedAudio.addEventListener("timeupdate", () => {
      updateAllPlayers();
      writeStoredPlayerState();
    });
    sharedAudio.addEventListener("ended", () => {
      updateAllPlayers();
      writeStoredPlayerState();
    });
    return sharedAudio;
  };

  const loadSharedAudio = (src) => {
    const audio = getSharedAudio();
    const absoluteSrc = absoluteAudioSrc(src);
    if (!absoluteSrc) return audio;
    if (sharedAudioSrc !== absoluteSrc) {
      sharedAudioSrc = absoluteSrc;
      pendingSeekTime = null;
      audio.src = src;
      audio.load();
    }
    return audio;
  };

  const updateAllPlayers = () => {
    if (!sharedAudio) return;
    playerBindings.forEach((binding) => {
      const isActive = binding.absoluteSrc && binding.absoluteSrc === sharedAudioSrc;
      const isPlaying = isActive && !sharedAudio.paused;
      const displayTime = pendingSeekTime ?? sharedAudio.currentTime;
      const current = isActive ? displayTime : 0;
      const loadedDuration = Number.isFinite(sharedAudio.duration) ? sharedAudio.duration : 0;
      const duration = isActive && loadedDuration > 0 ? loadedDuration : binding.initialDuration;
      const value = isActive && duration > 0
        ? Math.min(100, (current / duration) * 100)
        : 0;

      binding.player.classList.toggle("is-active-player", Boolean(isActive));
      binding.player.classList.toggle("is-playing", Boolean(isPlaying));
      binding.button?.classList.toggle("is-playing", Boolean(isPlaying));
      binding.button?.setAttribute("aria-pressed", String(isPlaying));
      binding.button?.setAttribute("aria-label", isPlaying ? "에피소드 일시정지" : "에피소드 재생");
      if (binding.currentTime) binding.currentTime.textContent = formatTime(current);
      binding.durationLabel.textContent =
        Number.isFinite(duration) && duration > 0
          ? formatTime(duration)
          : binding.durationLabel.dataset.initialDuration || "0:00";
      binding.bar?.style.setProperty("--value", `${value}%`);
      binding.progress?.setAttribute("aria-valuenow", String(Math.round(value)));
    });
    updateTranscriptHighlight(pendingSeekTime ?? sharedAudio.currentTime ?? 0);
  };

  const restoreSharedAudioState = () => {
    const stored = readStoredPlayerState();
    if (!stored?.src) return;
    const binding = playerBindings.find((item) => item.absoluteSrc === stored.src);
    if (!binding) return;
    const audio = loadSharedAudio(binding.src);
    const resumeAt = Number(stored.currentTime) || 0;
    if (resumeAt <= 0) {
      updateAllPlayers();
      return;
    }
    const restoreTime = () => {
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        audio.currentTime = Math.min(resumeAt, Math.max(0, audio.duration - 0.25));
      } else {
        audio.currentTime = resumeAt;
      }
      updateAllPlayers();
    };
    if (audio.readyState >= 1) {
      restoreTime();
    } else {
      audio.addEventListener("loadedmetadata", restoreTime, { once: true });
    }
  };

  const updateTranscriptHighlight = (currentTime) => {
    const rows = Array.from(document.querySelectorAll("[data-transcript-start]"));
    if (!rows.length) return;
    let activeRow = rows[0];
    rows.forEach((row) => {
      const start = Number(row.dataset.transcriptStart) || 0;
      if (start <= currentTime + TRANSCRIPT_HIGHLIGHT_TOLERANCE_SECONDS) activeRow = row;
      row.classList.remove("is-active");
      row.removeAttribute("aria-current");
    });
    activeRow.classList.add("is-active");
    activeRow.setAttribute("aria-current", "true");
  };

  const seekSharedAudio = (src, startSeconds, { play = false } = {}) => {
    const audio = loadSharedAudio(src);
    const start = Math.max(0, Number(startSeconds) || 0);
    const applySeek = () => {
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        audio.currentTime = Math.min(start, Math.max(0, audio.duration - 0.25));
      } else {
        audio.currentTime = start;
      }
      pendingSeekTime = null;
      updateAllPlayers();
      if (play) audio.play().catch(() => updateAllPlayers());
    };

    pendingSeekTime = start;
    if (audio.readyState >= 1) {
      applySeek();
    } else {
      updateAllPlayers();
      audio.addEventListener("loadedmetadata", applySeek, { once: true });
      audio.load();
    }
  };

  const seekSharedAudioRatio = (src, ratio, fallbackDuration = 0) => {
    const audio = loadSharedAudio(src);
    const targetRatio = Math.max(0, Math.min(1, Number(ratio) || 0));
    const fallback = Math.max(0, Number(fallbackDuration) || 0);
    const setPendingDisplay = () => {
      if (fallback > 0) {
        pendingSeekTime = targetRatio * fallback;
        updateAllPlayers();
      }
    };
    const applySeek = () => {
      const duration = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : fallback;
      if (duration <= 0) {
        setPendingDisplay();
        return;
      }
      pendingSeekTime = null;
      audio.currentTime = Math.min(targetRatio * duration, Math.max(0, duration - 0.25));
      updateAllPlayers();
    };

    setPendingDisplay();
    if (audio.readyState >= 1) {
      applySeek();
    } else {
      audio.addEventListener("loadedmetadata", applySeek, { once: true });
      audio.load();
    }
  };

  const initTranscriptNavigation = (audioSrc) => {
    if (!audioSrc) return;
    document.querySelectorAll("[data-transcript-start]").forEach((row) => {
      const start = Number(row.dataset.transcriptStart) || 0;
      row.setAttribute("role", "button");
      row.setAttribute("tabindex", "0");
      if (row.dataset.transcriptDescription) {
        row.setAttribute("aria-describedby", row.dataset.transcriptDescription);
      }
      const activate = () => seekSharedAudio(audioSrc, start, { play: true });
      row.addEventListener("click", activate);
      row.addEventListener("keydown", (event) => {
        if (!["Enter", " "].includes(event.key)) return;
        event.preventDefault();
        activate();
      });
    });
  };

  const playerAudioAttr = (audioSrc) => `data-audio-src="${escapeAttr(audioSrc || "")}"`;

  const inlinePlayerMarkup = ({ title, audioSrc, duration = "0:00", variant = "" }) => `
    <div class="inline-player ${escapeAttr(variant)}" data-player ${playerAudioAttr(audioSrc)}>
      <button class="play-button" type="button" aria-label="에피소드 재생"></button>
      <div class="audio-stack">
        <strong>${escapeHtml(title || "이번 주 식물 육종 브리핑")}</strong>
        <div class="progress" data-seek-bar role="slider" aria-label="재생 위치" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" tabindex="0">
          <span class="progress__bar" style="--value: 0%"></span>
        </div>
        <div class="time-row"><span data-current-time>0:00</span><span data-duration>${escapeHtml(duration)}</span></div>
      </div>
    </div>
  `;

  const buildFloatingPlayer = ({ title, subtitle, audioSrc, duration = "2:15" }) => `
    <div class="floating-player" data-player ${playerAudioAttr(audioSrc)}>
      <button class="play-button" type="button" aria-label="에피소드 재생"></button>
      <div class="floating-title">
        <strong>${escapeHtml(title)}</strong>
        <span>${escapeHtml(subtitle || "지윤 · 민종")}</span>
      </div>
      <div class="audio-stack">
        <div class="progress" data-seek-bar role="slider" aria-label="재생 위치" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" tabindex="0">
          <span class="progress__bar" style="--value: 0%"></span>
        </div>
        <div class="time-row"><span data-current-time>0:00</span><span data-duration>${escapeHtml(duration)}</span></div>
      </div>
      <div class="floating-actions" aria-label="오디오 동작">
        <a class="icon-button" href="${baseUrl}/podcast/feed.xml" aria-label="RSS">RSS</a>
        ${audioSrc ? `<a class="icon-button" href="${escapeAttr(audioSrc)}" download aria-label="오디오 다운로드">↓</a>` : ""}
      </div>
    </div>
  `;

  const initPlayers = () => {
    const audio = getSharedAudio();
    playerBindings = Array.from(document.querySelectorAll("[data-player]"))
      .map((player) => {
        const nativeAudio = player.querySelector("audio");
        const src = player.dataset.audioSrc || nativeAudio?.getAttribute("src") || "";
        if (nativeAudio) {
          nativeAudio.pause();
          nativeAudio.removeAttribute("src");
          nativeAudio.load();
          nativeAudio.hidden = true;
        }
        const button = player.querySelector(".play-button");
        const progress = player.querySelector("[data-seek-bar], .progress");
        const durationLabel = player.querySelector("[data-duration]");
        const initialDurationText = durationLabel?.textContent || "0:00";
        const initialDuration = initialDurationText
          .split(":")
          .map((part) => Number(part))
          .reduce((total, value) => (Number.isFinite(value) ? total * 60 + value : total), 0);
        return {
          player,
          src,
          absoluteSrc: absoluteAudioSrc(src),
          button,
          progress,
          bar: player.querySelector(".progress__bar"),
          currentTime: player.querySelector("[data-current-time]"),
          durationLabel,
          initialDuration,
        };
      })
      .filter((binding) => binding.src && binding.button && binding.durationLabel);

    playerBindings.forEach((binding) => {
      binding.durationLabel.dataset.initialDuration = binding.durationLabel.textContent || "0:00";
      const bar = binding.player.querySelector(".progress__bar");
      if (bar && !binding.bar) binding.bar = bar;
      binding.button.addEventListener("click", () => {
        const isSameSource = binding.absoluteSrc === sharedAudioSrc;
        if (isSameSource && !audio.paused) {
          audio.pause();
          return;
        }
        loadSharedAudio(binding.src);
        updateAllPlayers();
        audio.play().catch(() => updateAllPlayers());
      });

      const seek = (event) => {
        loadSharedAudio(binding.src);
        const rect = binding.progress.getBoundingClientRect();
        const pointerX = event.clientX ?? event.touches?.[0]?.clientX ?? rect.left;
        const ratio = Math.max(0, Math.min(1, (pointerX - rect.left) / rect.width));
        seekSharedAudioRatio(binding.src, ratio, binding.initialDuration);
      };
      binding.progress?.addEventListener("click", seek);
      binding.progress?.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        loadSharedAudio(binding.src);
        const duration = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : binding.initialDuration;
        if (duration <= 0) {
          updateAllPlayers();
          return;
        }
        const current = binding.absoluteSrc === sharedAudioSrc ? pendingSeekTime ?? audio.currentTime : 0;
        if (event.key === "Home") seekSharedAudio(binding.src, 0);
        if (event.key === "End") seekSharedAudio(binding.src, duration);
        if (event.key === "ArrowLeft") seekSharedAudio(binding.src, Math.max(0, current - 10));
        if (event.key === "ArrowRight") seekSharedAudio(binding.src, Math.min(duration, current + 10));
      });
    });
    restoreSharedAudioState();
    updateAllPlayers();
    window.addEventListener("pagehide", writeStoredPlayerState);
  };

  const queueMarkup = (items) => `
    <aside class="queue">
      <p class="kicker">Now in queue</p>
      <h2>이번 에피소드 큐</h2>
      <div class="queue-list">
        ${items
          .slice(0, 5)
          .map(
            (item, index) => `
              <a class="queue-item" href="${escapeAttr(normalizeHref(item.href || item.itemPath || "#"))}">
                <span class="queue-index">${String(index + 1).padStart(2, "0")}</span>
                <span>
                  <strong class="queue-title">${escapeHtml(item.title)}</strong>
                  <span class="queue-meta">${escapeHtml(sourceDisplayName(item.source))} ${item.date ? `· ${escapeHtml(item.date)}` : ""}</span>
                </span>
              </a>
            `,
          )
          .join("")}
      </div>
    </aside>
  `;

  const buildHome = async () => {
    document.body.classList.add("view-home");
    deactivateSourceAnchors();
    if (window.location.hash) {
      window.scrollTo(0, 0);
    }
    const metadata = metadataFromHome();
    const podcast = await fetchPodcast();
    const highlights = parseItemsFromHeading("이번주 하이라이트");
    const recent = parseItemsFromHeading("최근 소식");
    const briefing = parseBriefing();
    const archive = parseArchive();
    const sources = parseSources();
    const audioSrc = podcast?.audio?.url ? `${baseUrl}/podcast/${podcast.audio.url}` : "";
    const episodeTitle = podcast?.title || "이번 주 식물 육종 브리핑";
    const displayEpisodeTitle = episodeTitle.replace(/^식물 육종 뉴스 팟캐스트\s*/, "");
    const episodeSubtitle = podcast?.shortDescription || "국산 밀, 기후 회복력, 종자 산업의 변화를 오디오로 정리했습니다.";
    const episodeHref = podcast?.releasedDate ? `${baseUrl}/podcast/${podcast.releasedDate}.html` : `${baseUrl}/podcast/`;
    const duration = podcast?.audio?.durationSeconds ? formatTime(podcast.audio.durationSeconds) : "2:15";
    const uniqueItems = (items) => {
      const seen = new Set();
      return items.filter((item) => {
        const key = item.href || `${item.title}-${item.date}`;
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    };
    const allItems = uniqueItems([...highlights, ...recent]);
    const leadStory = allItems[0] || highlights[0] || recent[0];
    const feedItems = allItems.filter((item) => item.href !== leadStory?.href).slice(0, 30);
    const feedSources = ["전체", ...Array.from(new Set(feedItems.map((item) => item.source).filter(Boolean)))];
    const signalCards = briefing.length
      ? briefing.slice(0, 3)
      : [
          { title: "핵심 변화", body: "식물 육종과 종자 산업에서 신호가 강한 소식을 먼저 보여줍니다." },
          { title: "기술 신호", body: "유전체, 기후 회복력, 품종 개발 관련 흐름을 우선 확인합니다." },
          { title: "시장 맥락", body: "정책과 현장 변화를 원문 기사로 바로 이어서 확인할 수 있습니다." },
        ];
    const newsCardMarkup = (item) => `
      <article class="news-card news-card--clickable feed-card" data-source="${escapeAttr(item.source)}">
        <a class="news-card__overlay" href="${escapeAttr(item.href)}" aria-label="${escapeAttr(`${item.title} 읽기`)}"></a>
        <div class="news-card__meta">
          <span class="source-badge">${escapeHtml(sourceDisplayName(item.source))}</span>
          <span>${escapeHtml(item.date || "latest")}</span>
        </div>
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.excerpt || "요약 정보가 제공되지 않은 소식입니다. 원문과 수집 데이터를 확인하세요.")}</p>
        <div class="card-actions">
          <span class="read-cue" aria-hidden="true">읽기</span>
          <a class="news-card__origin" href="${escapeAttr(item.originalHref || item.href)}">원문</a>
        </div>
      </article>
    `;
    const utilityLinks = (items, label) =>
      items.length
        ? items.map((item) => `<a href="${escapeAttr(item.href)}">${escapeHtml(item.title)}</a>`).join("")
        : `<span class="utility-empty">${escapeHtml(label)}</span>`;

    source.classList.add("is-hidden");
    const app = document.createElement("section");
    app.className = "home-experience";
    app.innerHTML = `
      <section class="home-dashboard">
        <div class="home-brief" id="briefing">
          <p class="kicker">Plant Breeding News</p>
          <h1>식물 육종 뉴스</h1>
          <p class="home-status">업데이트 ${escapeHtml(metadata.updated)} · 커버리지 ${escapeHtml(metadata.coverage)}</p>
          <div class="signal-list" aria-label="30초 브리핑">
            ${signalCards
            .map(
              (card, index) => `
                <article class="signal-row">
                  <span>${String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <strong>${escapeHtml(card.title)}</strong>
                    <p>${escapeHtml(card.body)}</p>
                  </div>
                </article>
              `,
            )
            .join("")}
          </div>
        </div>

        <aside class="home-lead-stack">
          <article class="lead-story news-card news-card--clickable" data-source="${escapeAttr(leadStory?.source || "news")}">
            <a class="news-card__overlay" href="${escapeAttr(leadStory?.href || "#")}" aria-label="${escapeAttr(`${leadStory?.title || "주요 뉴스"} 읽기`)}"></a>
            <div class="news-card__meta">
              <span class="source-badge">Lead</span>
              <span>${escapeHtml(sourceDisplayName(leadStory?.source))} ${leadStory?.date ? `· ${escapeHtml(leadStory.date)}` : ""}</span>
            </div>
            <h2>${escapeHtml(leadStory?.title || "이번 주 주요 뉴스")}</h2>
            <p>${escapeHtml(leadStory?.excerpt || "이번 주 식물 육종과 종자 산업에서 눈에 띄는 흐름을 먼저 확인하세요.")}</p>
            <div class="card-actions">
              <span class="read-cue" aria-hidden="true">읽기</span>
              <a class="news-card__origin" href="${escapeAttr(leadStory?.originalHref || leadStory?.href || "#")}">원문</a>
            </div>
          </article>

          <div class="podcast-strip">
            <div class="podcast-strip__copy">
              <p class="kicker">Podcast</p>
              <strong>${escapeHtml(displayEpisodeTitle)}</strong>
              <span>${escapeHtml(episodeSubtitle)}</span>
            </div>
            ${audioSrc ? inlinePlayerMarkup({ title: displayEpisodeTitle, audioSrc, duration, variant: "inline-player--compact" }) : ""}
            <a class="podcast-strip__link" href="${escapeAttr(episodeHref)}">대본 보기</a>
          </div>
        </aside>
      </section>

      <section class="section-block home-section" id="news-feed">
        <div class="section-head">
          <h2>뉴스 피드</h2>
          <p>하이라이트와 최신 소식을 하나의 목록으로 합쳐 중복 노출을 줄였습니다.</p>
        </div>
        <div class="source-filter" data-source-filter>
          ${filterButtonMarkup(feedSources)}
        </div>
        <p class="filter-status" data-results-status aria-live="polite"></p>
        <div class="filter-empty" data-empty-state hidden>조건에 맞는 뉴스가 없습니다. 검색어를 줄이거나 전체 출처로 다시 확인하세요.</div>
        <div class="news-feed-grid">
          ${feedItems.map(newsCardMarkup).join("")}
        </div>
      </section>

      <section class="section-block utility-panel" id="weekly-archive">
        <div class="utility-row">
          <strong>최근 브리핑</strong>
          <div class="utility-links">${utilityLinks(archive, "아직 생성된 브리핑이 없습니다.")}</div>
        </div>
        <div class="utility-row" id="sources">
          <strong>출처</strong>
          <div class="utility-links">${utilityLinks(sources, "등록된 출처가 없습니다.")}</div>
        </div>
      </section>
    `;
    source.after(app);
    initPlayers();
    initFilters();
    scrollToCurrentHash();
  };

  const parseEpisodeTranscript = () => {
    const heading = findHeading("h2", "대본");
    if (!heading) return [];
    const rows = [];
    for (let node = heading.nextElementSibling; node; node = node.nextElementSibling) {
      if (node.tagName === "H2") break;
      if (node.tagName !== "P") continue;
      const speaker = text(node.querySelector("strong")).replace(":", "") || "HOST";
      const line = text(node).replace(new RegExp(`^${speaker}:?\\s*`), "");
      rows.push({ speaker, line });
    }
    return rows;
  };

  const parseEpisodeDurationSeconds = () => {
    const durationLine = Array.from(source.querySelectorAll("li")).map(text).find((line) => line.includes("길이"));
    if (!durationLine) return 0;
    const korean = durationLine.match(/(\d+)\s*분\s*(\d+)\s*초/);
    if (korean) return Number(korean[1]) * 60 + Number(korean[2]);
    const timestamp = durationLine.match(/(\d+):(\d{2})/);
    if (timestamp) return Number(timestamp[1]) * 60 + Number(timestamp[2]);
    return 0;
  };

  const estimateTranscriptStarts = (transcript, durationSeconds) => {
    if (!transcript.length) return [];
    const weights = transcript.map((row) => Math.max(8, (row.line || "").length * 0.18 + 2));
    const totalWeight = weights.reduce((sum, value) => sum + value, 0) || 1;
    const estimatedDuration = durationSeconds || weights.reduce((sum, value) => sum + value, 0);
    let cursor = 0;
    return weights.map((weight) => {
      const start = cursor;
      cursor += (weight / totalWeight) * estimatedDuration;
      return Math.min(start, Math.max(0, estimatedDuration - 0.25));
    });
  };

  const buildPlayback = () => {
    document.body.classList.add("view-playback");
    const h1 = source.querySelector("h1");
    const title = text(h1) || "이번 주 식물 육종 브리핑";
    const summary = text(Array.from(source.querySelectorAll("p")).find((paragraph) => !paragraph.querySelector("strong")));
    const audio = source.querySelector("audio");
    const audioSrc = audio?.getAttribute("src") || "";
    const transcript = parseEpisodeTranscript();
    const durationSeconds = parseEpisodeDurationSeconds();
    const transcriptStarts = estimateTranscriptStarts(transcript, durationSeconds);
    const timestamps = transcriptStarts.map((start) => formatTime(start));

    deactivateSourceAnchors();
    source.classList.add("is-hidden");
    const app = document.createElement("section");
    app.className = "playback-experience";
    app.innerHTML = `
      <aside class="episode-rail">
        <p class="kicker">PBN Playback</p>
        <h1 class="cover-title" aria-label="${escapeAttr(title)}">
          <span class="cover-title__white">이번 주</span>
          <span class="cover-title__blue">식물</span>
          <span class="cover-title__cyan">육종</span>
          <span class="cover-title__green">브리핑</span>
        </h1>
        <div class="episode-art" aria-hidden="true">
          <div class="episode-art__label">
            <strong>${escapeHtml(title)}</strong>
            <span>AI TALK AUDIO</span>
          </div>
        </div>
        <div class="episode-meta">
          <p class="kicker">Episode</p>
          <h2>${escapeHtml(title)}</h2>
          <p>${escapeHtml(summary || "식물 육종과 종자 산업의 주요 흐름을 한국어 오디오로 정리했습니다.")}</p>
          ${inlinePlayerMarkup({
            title,
            audioSrc,
            duration: durationSeconds ? formatTime(durationSeconds) : "0:00",
            variant: "inline-player--rail",
          })}
        </div>
      </aside>
      <section class="transcript-panel">
        <div class="playback-topline">
          <a class="glass-pill" href="${baseUrl}/podcast/">에피소드</a>
          <a class="glass-pill" href="${baseUrl}/">뉴스</a>
          <a class="glass-pill" href="${baseUrl}/podcast/feed.xml">RSS</a>
        </div>
        <div class="transcript-list">
          ${transcript
            .map(
              (row, index) => `
                <span class="sr-only" id="transcript-action-${index}">${timestamps[index] || "0:00"}부터 재생하려면 클릭하거나 Enter 또는 Space를 누르세요.</span>
                <article class="transcript-row ${index === 0 ? "is-active" : ""}" data-transcript-start="${transcriptStarts[index] || 0}" data-transcript-index="${index}" data-transcript-description="transcript-action-${index}">
                  <span class="transcript-time">${timestamps[index] || ""}</span>
                  <div class="transcript-body">
                    <span class="speaker">${escapeHtml(row.speaker)}</span>
                    <p>${escapeHtml(row.line)}</p>
                  </div>
                </article>
              `,
            )
            .join("")}
        </div>
      </section>
      ${buildFloatingPlayer({
        title: `이번 주 식물 육종 브리핑: ${title}`,
        subtitle: "지윤 · 민종",
        audioSrc,
        duration: durationSeconds ? formatTime(durationSeconds) : "0:00",
      })}
    `;
    source.after(app);
    initPlayers();
    initTranscriptNavigation(audioSrc);
    initFilters();
  };

  const parsePodcastEpisodes = () => {
    const heading = findHeading("h2", "최신 에피소드");
    if (!heading) return [];
    return Array.from(siblingsUntilNextH2(heading))
      .filter((node) => node.tagName === "H3")
      .map((node) => {
        const link = node.querySelector("a");
        const description = text(node.nextElementSibling?.tagName === "P" ? node.nextElementSibling : null);
        return {
          title: text(link) || text(node),
          href: normalizeHref(link?.getAttribute("href") || "#"),
          description,
        };
      })
      .filter((episode) => episode.title);
  };

  const buildPodcastIndex = async () => {
    document.body.classList.add("view-podcast-index");
    const podcast = await fetchPodcast();
    const episodes = parsePodcastEpisodes();
    const latest = episodes[0] || {
      title: podcast?.title?.replace(/^식물 육종 뉴스 팟캐스트\s*/, "") || "이번 주 식물 육종 브리핑",
      href: podcast?.releasedDate ? `${baseUrl}/podcast/${podcast.releasedDate}.html` : "#",
      description: podcast?.shortDescription || "식물 육종과 종자 산업의 주요 흐름을 한국어 오디오로 정리했습니다.",
    };
    const audioSrc = podcast?.audio?.url ? `${baseUrl}/podcast/${podcast.audio.url}` : "";
    const duration = podcast?.audio?.durationSeconds ? formatTime(podcast.audio.durationSeconds) : "2:15";
    const queueItems = (podcast?.selectedItems || []).map((item) => ({
      title: item.title,
      href: item.itemPath ? `${baseUrl}/${item.itemPath}` : "#",
      source: item.source,
      date: item.date,
    }));

    deactivateSourceAnchors();
    source.classList.add("is-hidden");
    const app = document.createElement("section");
    app.className = "podcast-index-experience";
    app.innerHTML = `
      <section class="podcast-hero">
        <aside class="episode-rail">
          <p class="kicker">PBN Episodes</p>
          <h1 class="cover-title" aria-label="식물 육종 뉴스 에피소드">
            <span class="cover-title__white">뉴스를</span>
            <span class="cover-title__blue">듣는</span>
            <span class="cover-title__cyan">식물</span>
            <span class="cover-title__green">육종</span>
          </h1>
          <div class="episode-art" aria-hidden="true">
            <div class="episode-art__label">
              <strong>${escapeHtml(latest.title)}</strong>
              <span>AI TALK AUDIO</span>
            </div>
          </div>
        </aside>

        <div class="podcast-stage">
          <div class="podcast-topline">
            <span class="glass-pill">${escapeHtml(episodes.length || 1)} episodes</span>
            <a class="glass-pill" href="${baseUrl}/podcast/feed.xml">RSS</a>
          </div>
          <article class="current-episode podcast-feature" data-player ${playerAudioAttr(audioSrc)}>
            <p class="kicker">Latest episode</p>
            <h1>${escapeHtml(latest.title)}</h1>
            <p class="episode-subtitle">${escapeHtml(latest.description)}</p>
            <div class="episode-controls">
              <button class="play-button" type="button" aria-label="최신 에피소드 재생"></button>
              <div class="audio-stack">
                <div class="waveform" aria-hidden="true">${waveform()}</div>
                <div class="progress" data-seek-bar role="slider" aria-label="재생 위치" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" tabindex="0">
                  <span class="progress__bar" style="--value: 0%"></span>
                </div>
                <div class="time-row"><span data-current-time>0:00</span><span data-duration>${escapeHtml(duration)}</span></div>
              </div>
            </div>
            <div class="episode-links">
              <a class="episode-action episode-action--primary" href="${escapeAttr(latest.href)}">대본 보기</a>
              <a class="episode-action" href="${baseUrl}/podcast/feed.xml">RSS 구독</a>
            </div>
          </article>
        </div>
      </section>

      <section class="section-block">
        <div class="section-head">
          <h2>에피소드 라이브러리</h2>
          <p>브리핑을 먼저 듣고, 필요한 항목은 원문 뉴스로 이어서 확인하세요.</p>
        </div>
        <div class="episode-library">
          ${episodes
            .map(
              (episode, index) => `
                <a class="episode-card" href="${escapeAttr(episode.href)}">
                  <span>EP ${String(index + 1).padStart(2, "0")}</span>
                  <strong>${escapeHtml(episode.title)}</strong>
                  <p>${escapeHtml(episode.description)}</p>
                </a>
              `,
            )
            .join("")}
        </div>
      </section>

      <section class="section-block">
        <div class="section-head">
          <h2>이번 에피소드 큐</h2>
          <p>오디오에서 다루는 원본 뉴스 흐름입니다.</p>
        </div>
        <div class="episode-queue-grid">
          ${queueItems
            .slice(0, 6)
            .map(
              (item, index) => `
                <a class="queue-item queue-item--card" href="${escapeAttr(normalizeHref(item.href))}">
                  <span class="queue-index">${String(index + 1).padStart(2, "0")}</span>
                  <span>
                    <strong class="queue-title">${escapeHtml(item.title)}</strong>
                    <span class="queue-meta">${escapeHtml(sourceDisplayName(item.source))} ${item.date ? `· ${escapeHtml(item.date)}` : ""}</span>
                  </span>
                </a>
              `,
            )
            .join("")}
        </div>
      </section>
      ${buildFloatingPlayer({
        title: `이번 주 식물 육종 브리핑: ${latest.title}`,
        subtitle: "지윤 · 민종",
        audioSrc,
        duration,
      })}
    `;
    source.after(app);
    initPlayers();
    initFilters();
  };

  const sourceStats = (items) =>
    Object.entries(
      items.reduce((acc, item) => {
        acc[item.source] = (acc[item.source] || 0) + 1;
        return acc;
      }, {}),
    )
      .sort((a, b) => b[1] - a[1])
      .map(([sourceName, count]) => ({ sourceName, count }));

  const buildWeeklyBriefing = () => {
    document.body.classList.add("view-weekly-briefing");
    const title = text(source.querySelector("h1")) || "주간 요약";
    const range = title.match(/\(([^)]+)\)/)?.[1] || "최근 7일";
    const recent = parseItemsFromHeading("Recent");
    const stats = sourceStats(recent);
    const featured = recent[0];

    deactivateSourceAnchors();
    source.classList.add("is-hidden");
    const app = document.createElement("section");
    app.className = "weekly-briefing-experience";
    app.innerHTML = `
      <section class="briefing-hero">
        <div class="briefing-title-block">
          <p class="kicker">Weekly briefing</p>
          <h1>
            <span>이번 주</span>
            <span>식물 육종</span>
            <span class="cover-title__cyan">뉴스 브리핑</span>
          </h1>
          <p>${escapeHtml(range)} 동안 수집된 주요 뉴스를 출처와 맥락별로 정리했습니다.</p>
        </div>
        <aside class="briefing-stats" aria-label="브리핑 통계">
          <div>
            <span>${recent.length}</span>
            <strong>뉴스</strong>
          </div>
          <div>
            <span>${stats.length}</span>
            <strong>출처</strong>
          </div>
          <div>
            <span>${escapeHtml(range.split("~").pop()?.trim() || "latest")}</span>
            <strong>최신 업데이트</strong>
          </div>
        </aside>
      </section>

      <section class="briefing-focus">
        <article class="briefing-feature">
          <p class="kicker">Lead signal</p>
          <h2><a href="${escapeAttr(featured?.href || "#")}">${escapeHtml(featured?.title || "이번 주 주요 신호")}</a></h2>
          <p>${escapeHtml(featured?.excerpt || "이번 주 식물 육종과 종자 산업에서 눈에 띄는 흐름을 모았습니다.")}</p>
          <div class="card-actions">
            <a href="${escapeAttr(featured?.href || "#")}">읽기</a>
            <a href="${escapeAttr(featured?.originalHref || featured?.href || "#")}">원문</a>
          </div>
        </article>
        <div class="source-snapshot">
          <p class="kicker">Source mix</p>
          ${stats
            .map(
              (stat) => `
                <button type="button" data-source-jump="${escapeAttr(stat.sourceName)}">
                  <span>${escapeHtml(sourceDisplayName(stat.sourceName))}</span>
                  <strong>${stat.count}</strong>
                </button>
              `,
            )
            .join("")}
        </div>
      </section>

      <section class="section-block" id="weekly-news">
        <div class="section-head">
          <h2>뉴스 리스트</h2>
          <p>긴 주간 요약은 카드보다 행 단위 목록이 더 빠르게 스캔됩니다.</p>
        </div>
        <div class="source-filter" data-source-filter>
          ${filterButtonMarkup(["전체", ...stats.map((stat) => stat.sourceName)])}
        </div>
        <p class="filter-status" data-results-status aria-live="polite"></p>
        <div class="filter-empty" data-empty-state hidden>조건에 맞는 뉴스가 없습니다. 검색어를 줄이거나 전체 출처로 다시 확인하세요.</div>
        <div class="weekly-news-list">
          ${recent
            .map(
              (item, index) => `
                <article class="news-card weekly-news-row" data-source="${escapeAttr(item.source)}">
                  <span class="weekly-row-index">${String(index + 1).padStart(2, "0")}</span>
                  <div class="weekly-row-main">
                    <div class="news-card__meta">
                      <span class="source-badge">${escapeHtml(sourceDisplayName(item.source))}</span>
                      <span>${escapeHtml(item.date || "latest")}</span>
                    </div>
                    <h3><a href="${escapeAttr(item.href)}">${escapeHtml(item.title)}</a></h3>
                    <p>${escapeHtml(item.excerpt || "요약 정보가 제공되지 않은 소식입니다. 원문과 수집 데이터를 확인하세요.")}</p>
                  </div>
                  <div class="card-actions">
                    <a href="${escapeAttr(item.href)}">읽기</a>
                    <a href="${escapeAttr(item.originalHref || item.href)}">원문</a>
                  </div>
                </article>
              `,
            )
            .join("")}
        </div>
      </section>
    `;
    source.after(app);
    initFilters();
  };

  const initFilters = () => {
    const filter = document.querySelector("[data-source-filter]");
    const search = document.getElementById("pbn-search-input");
    const applyNewsFilters = () => {
      const selected = filter?.querySelector(".is-active")?.dataset.source || "전체";
      const query = (search?.value || "").trim().toLowerCase();
      const cards = Array.from(document.querySelectorAll(".news-card[data-source]"));
      let visibleCount = 0;
      cards.forEach((card) => {
        const sourceMatches = selected === "전체" || card.dataset.source === selected;
        const queryMatches = !query || card.textContent.toLowerCase().includes(query);
        card.hidden = !sourceMatches || !queryMatches;
        if (!card.hidden) visibleCount += 1;
      });

      const status = document.querySelector("[data-results-status]");
      const empty = document.querySelector("[data-empty-state]");
      if (status && cards.length) {
        const queryLabel = query ? `"${search.value.trim()}" 검색` : "전체 뉴스";
        const sourceLabel = selected === "전체" ? "전체 출처" : sourceDisplayName(selected);
        status.textContent = `${queryLabel} · ${sourceLabel} · ${visibleCount}건`;
      }
      if (empty) empty.hidden = visibleCount > 0;
    };

    const initialQuery = new URLSearchParams(window.location.search).get("q");
    if (search && initialQuery) search.value = initialQuery;

    search?.closest("form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const query = (search.value || "").trim();
      if (document.querySelector(".news-card[data-source]")) {
        applyNewsFilters();
        const target = document.getElementById("news-feed") || document.getElementById("weekly-news") || document.getElementById("recent");
        target?.scrollIntoView({ behavior: "smooth", block: "start" });
      } else if (query) {
        window.location.href = `${baseUrl}/?q=${encodeURIComponent(query)}`;
      }
    });

    search?.addEventListener("input", applyNewsFilters);
    applyNewsFilters();
    if (!filter) return;
    filter.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-source]");
      if (!button) return;
      filter.querySelectorAll("button").forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
      applyNewsFilters();
    });

    document.querySelectorAll("[data-source-jump]").forEach((button) => {
      button.addEventListener("click", () => {
        filter?.querySelector(`[data-source="${escapeSelectorValue(button.dataset.sourceJump)}"]`)?.click();
        document.getElementById("weekly-news")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  };

  const normalizedPage = pageUrl.replace(/\/index\.html$/, "/");
  const isHome =
    normalizedPage === "/" ||
    (text(source.querySelector("h1")) === "식물 육종 뉴스" && Boolean(source.querySelector("#highlights")));
  const isPodcastEpisode = Boolean(source.querySelector("audio")) && Boolean(findHeading("h2", "대본"));
  const isPodcastIndex = text(source.querySelector("h1")) === "식물 육종 뉴스 팟캐스트";
  const isWeeklyBriefing = text(source.querySelector("h1")).startsWith("주간 요약");

  setActiveNav();
  window.addEventListener("hashchange", () => {
    setActiveNav();
    scrollToCurrentHash();
  });

  if (isHome) {
    buildHome();
  } else if (isPodcastEpisode) {
    buildPlayback();
  } else if (isPodcastIndex) {
    buildPodcastIndex();
  } else if (isWeeklyBriefing) {
    buildWeeklyBriefing();
  } else {
    source.classList.remove("is-hidden");
    initFilters();
  }
})();
