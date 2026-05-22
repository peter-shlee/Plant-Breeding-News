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
    if (!href) return "#";
    if (/^(mailto:|tel:|#)/i.test(href)) return href;
    if (/^https?:/i.test(href)) {
      try {
        const url = new URL(href);
        url.pathname = url.pathname.replace(/\.md$/i, ".html");
        return url.href;
      } catch {
        return href;
      }
    }
    const hashIndex = href.indexOf("#");
    const queryIndex = href.indexOf("?");
    const splitIndex = [hashIndex, queryIndex].filter((index) => index >= 0).sort((a, b) => a - b)[0];
    const path = splitIndex >= 0 ? href.slice(0, splitIndex) : href;
    const suffix = splitIndex >= 0 ? href.slice(splitIndex) : "";
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
    const hash = window.location.hash;
    document.querySelectorAll(".pbn-nav a").forEach((link) => {
      const href = link.getAttribute("href") || "";
      const url = new URL(href, window.location.href);
      const targetPath = url.pathname.replace(/\/index\.html$/, "/");
      const isActive =
        (targetPath.endsWith("/podcast/") && normalizedPath.includes("/podcast/")) ||
        (targetPath.includes("/weekly/") && normalizedPath.includes("/weekly/")) ||
        (url.hash === "#recent" && normalizedPath.endsWith("/") && hash === "#recent") ||
        (url.hash === "#weekly-archive" && normalizedPath.endsWith("/") && hash === "#weekly-archive");
      link.classList.toggle("is-active", isActive);
      if (isActive) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  };

  const scrollToCurrentHash = () => {
    const id = decodeURIComponent(window.location.hash.slice(1));
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
      if (first) current.body = text(first);
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
      return `<span style="--h:${height}px"></span>`;
    }).join("");

  const formatTime = (seconds) => {
    if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.floor(seconds % 60);
    return `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
  };

  const buildFloatingPlayer = ({ title, subtitle, audioSrc, duration = "2:15" }) => `
    <div class="floating-player" data-player>
      <audio preload="metadata" src="${escapeAttr(audioSrc || "")}"></audio>
      <button class="play-button" type="button" aria-label="에피소드 재생"></button>
      <div class="floating-title">
        <strong>${escapeHtml(title)}</strong>
        <span>${escapeHtml(subtitle || "지윤 · 민종")}</span>
      </div>
      <div class="audio-stack">
        <div class="progress"><span class="progress__bar" style="--value: 0%"></span></div>
        <div class="time-row"><span data-current-time>0:00</span><span data-duration>${escapeHtml(duration)}</span></div>
      </div>
      <div class="floating-actions" aria-label="오디오 동작">
        <a class="icon-button" href="${baseUrl}/podcast/feed.xml" aria-label="RSS">RSS</a>
        ${audioSrc ? `<a class="icon-button" href="${escapeAttr(audioSrc)}" download aria-label="오디오 다운로드">↓</a>` : ""}
      </div>
    </div>
  `;

  const initPlayers = () => {
    document.querySelectorAll("[data-player]").forEach((player) => {
      const audio = player.querySelector("audio");
      const button = player.querySelector(".play-button");
      const bar = player.querySelector(".progress__bar");
      const currentTime = player.querySelector("[data-current-time]");
      const durationLabel = player.querySelector("[data-duration]");
      if (!audio || !button) return;

      const setButtonState = () => {
        const isPlaying = !audio.paused;
        button.classList.toggle("is-playing", isPlaying);
        button.setAttribute("aria-pressed", String(isPlaying));
        button.setAttribute("aria-label", isPlaying ? "에피소드 일시정지" : "에피소드 재생");
      };

      const updateTimeline = () => {
        if (currentTime) currentTime.textContent = formatTime(audio.currentTime);
        if (Number.isFinite(audio.duration) && audio.duration > 0) {
          if (durationLabel) durationLabel.textContent = formatTime(audio.duration);
          bar?.style.setProperty("--value", `${Math.min(100, (audio.currentTime / audio.duration) * 100)}%`);
        } else {
          bar?.style.setProperty("--value", "0%");
        }
      };

      setButtonState();
      updateTimeline();
      button.addEventListener("click", () => {
        if (audio.paused) {
          document.querySelectorAll("audio").forEach((other) => {
            if (other !== audio) other.pause();
          });
          audio.play().catch(() => {});
        } else {
          audio.pause();
        }
      });

      audio.addEventListener("play", setButtonState);
      audio.addEventListener("pause", setButtonState);
      audio.addEventListener("loadedmetadata", updateTimeline);
      audio.addEventListener("durationchange", updateTimeline);
      audio.addEventListener("timeupdate", updateTimeline);
    });
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
                  <span class="queue-meta">${escapeHtml(item.source || "news")} ${item.date ? `· ${escapeHtml(item.date)}` : ""}</span>
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
    const selectedItems = (podcast?.selectedItems || []).map((item) => ({
      title: item.title,
      href: item.itemPath ? normalizeHref(`${baseUrl}/${item.itemPath}`) : "#",
      source: item.source,
      date: item.date,
    }));
    const queueItems = selectedItems.length ? selectedItems : highlights;
    const audioSrc = podcast?.audio?.url ? `${baseUrl}/podcast/${podcast.audio.url}` : "";
    const episodeTitle = podcast?.title || "이번 주 식물 육종 브리핑";
    const displayEpisodeTitle = episodeTitle.replace(/^식물 육종 뉴스 팟캐스트\s*/, "");
    const episodeSubtitle = podcast?.shortDescription || "국산 밀, 기후 회복력, 종자 산업의 변화를 오디오로 정리했습니다.";
    const episodeHref = podcast?.releasedDate ? `${baseUrl}/podcast/${podcast.releasedDate}.html` : `${baseUrl}/podcast/`;
    const duration = podcast?.audio?.durationSeconds
      ? `${Math.floor(podcast.audio.durationSeconds / 60)}:${String(Math.round(podcast.audio.durationSeconds % 60)).padStart(2, "0")}`
      : "2:15";

    source.classList.add("is-hidden");
    const app = document.createElement("section");
    app.className = "home-experience";
    app.innerHTML = `
      <section class="home-hero">
        <aside class="episode-rail">
          <p class="kicker">Plant Breeding News</p>
          <h1 class="cover-title" aria-label="이번 주 식물 육종 브리핑">
            <span class="cover-title__white">이번 주</span>
            <span class="cover-title__blue">식물</span>
            <span class="cover-title__cyan">육종</span>
            <span class="cover-title__green">뉴스</span>
            <span class="cover-title__yellow">브리핑</span>
          </h1>
          <div class="episode-art" aria-hidden="true">
            <div class="episode-art__label">
              <strong>${escapeHtml(displayEpisodeTitle)}</strong>
              <span>AI TALK AUDIO</span>
            </div>
          </div>
          <div class="episode-meta">
            <p class="kicker">Episode</p>
            <h2>${escapeHtml(displayEpisodeTitle)}</h2>
            <p>${escapeHtml(episodeSubtitle)}</p>
            <p class="kicker" style="margin-top:20px">${escapeHtml(metadata.updated)} · ${escapeHtml(metadata.coverage)}</p>
          </div>
        </aside>

        <div class="listening-panel">
          <div class="home-topline">
            <span class="glass-pill">업데이트 ${escapeHtml(metadata.updated)}</span>
            <span class="glass-pill">커버리지 ${escapeHtml(metadata.coverage)}</span>
          </div>
          <section class="hero-player">
            <div class="current-episode" data-player>
              <audio preload="metadata" src="${escapeAttr(audioSrc)}"></audio>
              <p class="kicker">Latest episode</p>
              <h1>${escapeHtml(displayEpisodeTitle)}</h1>
              <p class="episode-subtitle">${escapeHtml(episodeSubtitle)}</p>
              <div class="episode-controls">
                <button class="play-button" type="button" aria-label="최신 에피소드 재생"></button>
                <div class="audio-stack">
                  <div class="waveform" aria-hidden="true">${waveform()}</div>
                  <div class="progress"><span class="progress__bar" style="--value: 0%"></span></div>
                  <div class="time-row"><span data-current-time>0:00</span><span data-duration>${escapeHtml(duration)}</span></div>
                </div>
              </div>
              <div class="episode-links">
                <a class="episode-action episode-action--primary" href="${escapeAttr(episodeHref)}">에피소드 열기</a>
                <a class="episode-action" href="${baseUrl}/podcast/feed.xml">RSS</a>
              </div>
            </div>
            ${queueMarkup(queueItems)}
          </section>
        </div>
      </section>

      <section class="section-block" id="highlights">
        <div class="section-head">
          <h2>이번주 하이라이트</h2>
          <p>원본 자동 생성 페이지의 하이라이트 링크를 전체 유지했습니다.</p>
        </div>
        <div class="news-grid">
          ${highlights
            .map(
              (item) => `
                <article class="news-card" data-source="${escapeAttr(item.source)}">
                  <div class="news-card__meta">
                    <span class="source-badge">${escapeHtml(item.source)}</span>
                    <span>${escapeHtml(item.date || "latest")}</span>
                  </div>
                  <h3><a href="${escapeAttr(item.href)}">${escapeHtml(item.title)}</a></h3>
                  <p>${escapeHtml(item.excerpt || "요약 정보가 제공되지 않은 소식입니다. 원문과 수집 데이터를 확인하세요.")}</p>
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

      <section class="section-block" id="briefing">
        <div class="section-head">
          <h2>30초 브리핑</h2>
          <p>긴 뉴스 목록을 바로 듣고 싶은 요점으로 압축했습니다.</p>
        </div>
        <div class="brief-grid">
          ${briefing
            .map(
              (card) => `
                <article class="brief-card">
                  <p class="kicker">Signal</p>
                  <h3>${escapeHtml(card.title)}</h3>
                  <p>${escapeHtml(card.body)}</p>
                </article>
              `,
            )
            .join("")}
        </div>
      </section>

      <section class="section-block" id="recent">
        <div class="section-head">
          <h2>최신 뉴스</h2>
          <p>새 소식을 읽기 전에 큐에 올려두고 흐름부터 들어보세요.</p>
        </div>
        <div class="source-filter" data-source-filter>
          ${["전체", "rda", "nics", "nihhs", "seedworld", "sciencedaily"]
            .map((label, index) => `<button type="button" class="${index === 0 ? "is-active" : ""}" data-source="${label}">${label}</button>`)
            .join("")}
        </div>
        <div class="news-grid">
          ${recent
            .map(
              (item) => `
                <article class="news-card" data-source="${escapeAttr(item.source)}">
                  <div class="news-card__meta">
                    <span class="source-badge">${escapeHtml(item.source)}</span>
                    <span>${escapeHtml(item.date || "latest")}</span>
                  </div>
                  <h3><a href="${escapeAttr(item.href)}">${escapeHtml(item.title)}</a></h3>
                  <p>${escapeHtml(item.excerpt || "요약 정보가 제공되지 않은 소식입니다. 원문과 수집 데이터를 확인하세요.")}</p>
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

      <section class="section-block" id="weekly-archive">
        <div class="section-head">
          <h2>지난 브리핑</h2>
          <p>주차별 흐름을 다시 읽고 에피소드로 이어서 확인하세요.</p>
        </div>
        <div class="archive-tiles">
          ${archive
            .map(
              (item, index) => `
                <a class="episode-tile" href="${escapeAttr(item.href)}">
                  <span>EP ${String(index + 1).padStart(2, "0")}</span>
                  <strong>${escapeHtml(item.title)}</strong>
                </a>
              `,
            )
            .join("")}
        </div>
      </section>

      <section class="section-block" id="sources">
        <div class="section-head">
          <h2>출처별 모아보기</h2>
          <p>자동 수집된 기존 출처별 목록 링크를 그대로 유지했습니다.</p>
        </div>
        <div class="source-tiles">
          ${sources
            .map(
              (item) => `
                <a class="source-tile" href="${escapeAttr(item.href)}">
                  <span>Source</span>
                  <strong>${escapeHtml(item.title)}</strong>
                </a>
              `,
            )
            .join("")}
        </div>
      </section>
      ${buildFloatingPlayer({
        title: `이번 주 식물 육종 브리핑: ${displayEpisodeTitle}`,
        subtitle: "지윤 · 민종",
        audioSrc,
        duration,
      })}
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

  const buildPlayback = () => {
    document.body.classList.add("view-playback");
    const h1 = source.querySelector("h1");
    const title = text(h1) || "이번 주 식물 육종 브리핑";
    const summary = text(Array.from(source.querySelectorAll("p")).find((paragraph) => !paragraph.querySelector("strong")));
    const audio = source.querySelector("audio");
    const audioSrc = audio?.getAttribute("src") || "";
    const transcript = parseEpisodeTranscript();
    const timestamps = ["0:00", "0:13", "0:46", "1:19", "1:26", "2:01", "2:34", "3:02"];

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
          <div class="native-audio-shell">
            <audio controls preload="metadata" src="${escapeAttr(audioSrc)}"></audio>
          </div>
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
                <article class="transcript-row ${index === 0 ? "is-active" : ""}">
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
        duration: "2:15",
      })}
    `;
    source.after(app);
    initPlayers();
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
          <article class="current-episode podcast-feature" data-player>
            <audio preload="metadata" src="${escapeAttr(audioSrc)}"></audio>
            <p class="kicker">Latest episode</p>
            <h1>${escapeHtml(latest.title)}</h1>
            <p class="episode-subtitle">${escapeHtml(latest.description)}</p>
            <div class="episode-controls">
              <button class="play-button" type="button" aria-label="최신 에피소드 재생"></button>
              <div class="audio-stack">
                <div class="waveform" aria-hidden="true">${waveform()}</div>
                <div class="progress"><span class="progress__bar" style="--value: 0%"></span></div>
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
                    <span class="queue-meta">${escapeHtml(item.source || "news")} ${item.date ? `· ${escapeHtml(item.date)}` : ""}</span>
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
                  <span>${escapeHtml(stat.sourceName)}</span>
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
          ${["전체", ...stats.map((stat) => stat.sourceName)]
            .map((label, index) => `<button type="button" class="${index === 0 ? "is-active" : ""}" data-source="${escapeAttr(label)}">${escapeHtml(label)}</button>`)
            .join("")}
        </div>
        <div class="weekly-news-list">
          ${recent
            .map(
              (item, index) => `
                <article class="news-card weekly-news-row" data-source="${escapeAttr(item.source)}">
                  <span class="weekly-row-index">${String(index + 1).padStart(2, "0")}</span>
                  <div class="weekly-row-main">
                    <div class="news-card__meta">
                      <span class="source-badge">${escapeHtml(item.source)}</span>
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
      document.querySelectorAll(".news-card[data-source]").forEach((card) => {
        const sourceMatches = selected === "전체" || card.dataset.source === selected;
        const queryMatches = !query || card.textContent.toLowerCase().includes(query);
        card.hidden = !sourceMatches || !queryMatches;
      });
    };

    const initialQuery = new URLSearchParams(window.location.search).get("q");
    if (search && initialQuery) search.value = initialQuery;

    search?.closest("form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const query = (search.value || "").trim();
      if (document.querySelector(".news-card[data-source]")) {
        document.getElementById("recent")?.scrollIntoView({ behavior: "smooth", block: "start" });
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
