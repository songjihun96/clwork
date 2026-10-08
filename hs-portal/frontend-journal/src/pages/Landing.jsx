import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

/** 기록해 첫 화면(로그인 전). 디자인 기준: "기록해 첫 화면.pdf".
 *
 *  흐름을 한눈에: 매일 기록 → 자기소개서 문항에 연결 → 필요할 때 꺼내 쓴다.
 *  **실제로 있는 기능만 소개한다.** NCS 는 기능이 아니라 '질문에 답하는 습관이 어떤
 *  능력과 맞닿아 있는지'를 설명하는 데만 쓴다(NCS 분석 기능은 없다).
 *  자기소개서 영역의 일지는 예시(실제 학생 기록이 아님)라고 밝힌다.
 */

// 서버(/api/journal-meta)가 못 오면 쓰는 문항 목록. 서버 값과 같은 순서다.
const FALLBACK_TOPICS = [
  "자신의 강점을 강화시키고 약점을 관리했던 경험",
  "직무와 관련된 역량을 키우던 중 자신이 맡았던 역할과 문제 발생 시 해결했던 경험",
  "팀 활동에서 본인의 역할을 책임감 있게 수행했던 경험",
  "팀/개인적으로 사람과의 관계에서 힘들었던 갈등 상황과 극복 경험",
  "팀/조직의 중요한 규정이나 지침, 원칙을 지키기 위해 노력한 경험",
  "팀/조직의 이익을 위해 자신이 희생했던 경험",
  "팀/개인적으로 도전과 목표를 성취했던 경험",
  "계획대로 되지 않았거나 실패했던 경험과, 그 과정에서 배웠던 경험",
  "자신의 부족한 점과 이를 보완하기 위해 현재 하고 있는 노력",
  "새로운 지식이나 기술을 배우기 위해 스스로 노력했던 경험",
  "해당 직무(분야)를 선택하게 된 계기와 그 직무를 위해 준비해 온 것",
];

// 예시 기록. 문항 번호(1부터)에 묶는다.
const SAMPLE = {
  2: [
    { kind: "수업일지", date: "10월 7일 · 공통수학1", title: "이차함수 그래프 평행이동",
      text: "부호가 헷갈려 막혔지만 꼭짓점을 직접 대입해 확인하며 해결. 원리를 확인하는 습관을 얻음." },
    { kind: "수업일지", date: "9월 24일 · 전공실습", title: "회로 납땜 불량 찾기",
      text: "작동하지 않는 원인을 테스터로 구간별 측정해 찾아냄. 순서대로 점검하는 방법을 익힘." },
  ],
  3: [
    { kind: "학교생활일지", date: "9월 12일", title: "체육대회 반 대표 계주",
      text: "바통 넘기는 순서를 정하고 점심시간마다 연습을 이끌었다. 맡은 역할을 끝까지 해내는 책임감을 느꼈다." },
  ],
  4: [
    { kind: "학교생활일지", date: "9월 3일", title: "모둠 과제 역할 갈등",
      text: "역할 분담 문제로 다툼이 생겼지만 각자 할 일을 표로 정리해 다시 나눴다. 먼저 이야기를 듣는 것이 중요했다." },
  ],
  10: [
    { kind: "수업일지", date: "10월 2일 · 프로그래밍", title: "반복문 혼자 연습",
      text: "range 끝 값이 헷갈려 코드를 직접 바꿔 실행해 보며 익혔다. 모르면 직접 실행해 보는 습관이 생겼다." },
  ],
};

const NCS = [
  { title: "의사소통능력", text: "배운 내용을 내 언어로 정리하고, 남이 읽어도 이해되는 글을 쓰는 연습이 됩니다.",
    tags: ["수업일지", "학교생활일지"] },
  { title: "문제해결능력", text: "어려웠던 점 → 해결 방법 → 결과를 매번 적으며 문제를 풀어 간 과정을 정리합니다.",
    tags: ["수업일지", "학교생활일지"] },
  { title: "자기개발능력", text: "스스로 학습 상태를 점검하고 돌아보며, 앞으로 실천할 점을 정하는 습관이 생깁니다.",
    tags: ["수업일지", "학교생활일지"] },
  { title: "정보능력", text: "수업에서 다룬 내용을 추려 핵심만 요약해 남기는 연습이 됩니다.",
    tags: ["수업일지"] },
];

function useReveal() {
  const ref = useRef(null);
  useEffect(() => {
    const root = ref.current;
    if (!root) return undefined;
    const els = root.querySelectorAll(".lp-reveal");
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !("IntersectionObserver" in window)) {
      els.forEach((e) => e.classList.add("in"));
      return undefined;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px" });
    els.forEach((e) => io.observe(e));
    return () => io.disconnect();
  }, []);
  return ref;
}

const kindClass = (k) => (k === "수업일지" ? "lp-tag lesson" : "lp-tag diary");

export default function Landing() {
  const ref = useReveal();
  useEffect(() => {
    const before = document.title;
    document.title = "기록해 | 학교생활과 수업을 기록하고 자기소개서로 연결";
    return () => { document.title = before; };
  }, []);
  return (
    <div className="lp" ref={ref}>
      <HeroSection />
      <HowItWorksSection />
      <DiaryTypesSection />
      <NCSSection />
      <ResumeSection />
      <FeatureSection />
      <CTASection />
    </div>
  );
}

function HeroSection() {
  return (
    <section className="lp-hero" aria-labelledby="lp-hero-title">
      <div className="wrap lp-hero-inner">
        <div>
          <span className="lp-pill">특성화고 학생을 위한 수업·학교생활 기록장</span>
          <h1 id="lp-hero-title" className="lp-h1">
            오늘의 수업이<br />내일의 <em>자기소개서</em>가 됩니다
          </h1>
          <p className="lp-lead">
            매일 배운 것, 막혔던 것, 해결한 과정을 짧게 남기고 자기소개서 문항에 미리 연결해 두세요.
            막상 자소서를 쓸 때 &ldquo;쓸 경험이 없다&rdquo;는 고민이 줄어듭니다.
          </p>
          <div className="lp-cta-row">
            <Link className="btn btn-primary lp-btn" to="/signup">오늘 기록 시작하기</Link>
            <a className="btn lp-btn" href="#how">어떻게 쓰나요?</a>
          </div>
          <p className="lp-note">선생님께 제출하는 기능은 무료입니다.</p>
        </div>

        <div className="lp-hero-visual" aria-label="기록이 자기소개서와 연결되는 예시">
          <div className="lp-card lp-record">
            <div className="lp-card-head">
              <span className="lp-tag lesson">수업일지</span>
              <span className="lp-muted">10월 7일 · 공통수학1</span>
            </div>
            <b className="lp-card-title">이차함수 그래프 평행이동</b>
            <ul className="lp-kv">
              <li><b>어려웠던 점</b> · 이동 방향과 부호가 자꾸 반대로 헷갈렸다</li>
              <li><b>해결 방법</b> · 꼭짓점 하나를 직접 대입해 보며 확인했다</li>
              <li><b>느낀 점</b> · 공식보다 원리를 확인하는 습관이 필요하다</li>
            </ul>
          </div>
          <div className="lp-link-line" aria-hidden="true">↓ <span>자기소개서 2번 문항에 연결됨</span></div>
          <div className="lp-card lp-resume">
            <span className="lp-muted-inv">자기소개서 · 문항 2</span>
            <b>직무와 관련된 역량을 키우던 중 맡았던 역할과 문제 발생 시 해결했던 경험</b>
            <div className="lp-chips"><span>수업일지 3건</span><span>학교생활일지 1건</span></div>
          </div>
        </div>
      </div>
    </section>
  );
}

function HowItWorksSection() {
  const steps = [
    ["01", "매일 기록한다", "수업이 끝나면 수업일지를, 하루를 마치면 학교생활일지를 씁니다. 정해진 질문에 답하기만 하면 되니 길게 쓰지 않아도 괜찮아요."],
    ["02", "자소서 문항에 연결한다", "저장하기 전에 오늘 기록이 자기소개서 11개 문항 중 어디에 쓰이면 좋을지 체크합니다. 여러 개를 골라도 됩니다."],
    ["03", "필요할 때 꺼내 쓴다", "자기소개서 탭에서 문항을 선택하면 그 문항에 연결해 둔 일지가 바로 옆에 나타납니다. 내 기록을 재료 삼아 써 내려가세요."],
  ];
  return (
    <section id="how" className="lp-section lp-white" aria-labelledby="lp-how">
      <div className="wrap">
        <span className="lp-eyebrow">이용 방법</span>
        <h2 id="lp-how" className="lp-h2">기록하고, 연결하고, 꺼내 쓰세요</h2>
        <div className="lp-steps">
          {steps.map(([n, t, d]) => (
            <div key={n} className="lp-step lp-reveal">
              <span className="lp-step-no">{n}</span>
              <b>{t}</b>
              <p>{d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function DiaryTypesSection() {
  const types = [
    { tag: "수업일지", cls: "lesson", title: "오늘 수업에서 배운 것과 해결 과정",
      desc: "무엇을 배웠고, 어디서 막혔고, 어떻게 풀었는지를 남깁니다.",
      items: ["수업 내용과 수업을 통해 느낀 점", "해결하지 못한 부분과 해결 계획",
              "해결한 내용, 해결 과정과 결과, 얻은 교훈", "연결할 자기소개서 문항 체크"] },
    { tag: "학교생활일지", cls: "diary", title: "오늘 가장 기억에 남는 일",
      desc: "활동·관계·사건에서 깨달은 것과 앞으로의 실천을 남깁니다.",
      items: ["가장 기억에 남는 수업·활동·사건", "기억에 남는 이유",
              "얻게 된 교훈 또는 깨달은 부분", "실천하고 적용할 수 있는 부분, 연결할 문항 체크"] },
  ];
  return (
    <section id="diaries" className="lp-section" aria-labelledby="lp-diaries">
      <div className="wrap">
        <span className="lp-eyebrow">두 가지 일지</span>
        <h2 id="lp-diaries" className="lp-h2">질문에 답하다 보면<br />경험이 이야기로 정리됩니다</h2>
        <div className="lp-types">
          {types.map((t) => (
            <div key={t.tag} className="lp-type lp-reveal">
              <span className={`lp-tag ${t.cls}`}>{t.tag}</span>
              <b className="lp-type-title">{t.title}</b>
              <p className="lp-muted">{t.desc}</p>
              <ol>
                {t.items.map((it) => <li key={it}>{it}</li>)}
              </ol>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function NCSSection() {
  return (
    <section id="ncs" className="lp-section lp-navy" aria-labelledby="lp-ncs">
      <div className="wrap">
        <span className="lp-eyebrow inv">NCS 직업기초능력</span>
        <h2 id="lp-ncs" className="lp-h2">쓰는 습관이 곧 역량이 됩니다</h2>
        <p className="lp-lead inv">
          기록해의 질문에 답하는 과정은 취업 현장에서 말하는 NCS 직업기초능력 가운데 몇 가지와
          맞닿아 있습니다. 쌓인 기록은 면접에서 경험을 근거로 답할 때 도움이 됩니다.
        </p>
        <div className="lp-ncs">
          {NCS.map((c) => (
            <div key={c.title} className="lp-ncs-card lp-reveal">
              <b>{c.title}</b>
              <p>{c.text}</p>
              <div className="lp-chips light">
                {c.tags.map((t) => <span key={t} className={kindClass(t)}>{t}</span>)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function ResumeSection() {
  const [topics, setTopics] = useState(FALLBACK_TOPICS);
  const [active, setActive] = useState(2);
  useEffect(() => {
    api.journalMeta().then((m) => {
      const list = (m.resume_categories || []).map((c) => c.label).filter(Boolean);
      if (list.length) setTopics(list);
    }).catch(() => {});
  }, []);
  const records = SAMPLE[active] || [];
  return (
    <section id="resume" className="lp-section" aria-labelledby="lp-resume">
      <div className="wrap">
        <span className="lp-eyebrow">자기소개서</span>
        <h2 id="lp-resume" className="lp-h2">문항을 고르면, 쓸 재료가 먼저 와 있습니다</h2>
        <p className="lp-muted">아래 문항을 눌러 보세요. 그 문항에 연결해 둔 일지가 옆에 나타납니다. <b>(예시 기록)</b></p>
        <div className="lp-resume">
          <ol className="lp-topics" aria-label="자기소개서 문항">
            {topics.map((t, i) => {
              const n = i + 1;
              const cnt = (SAMPLE[n] || []).length;
              return (
                <li key={t}>
                  <button type="button" className={`lp-topic${active === n ? " on" : ""}`}
                    aria-pressed={active === n} onClick={() => setActive(n)}>
                    <span className="lp-topic-no">{n}</span>
                    <span className="lp-topic-text">{t}</span>
                    {cnt > 0 && <span className="lp-topic-cnt">기록 {cnt}건</span>}
                  </button>
                </li>
              );
            })}
          </ol>
          <div className="lp-picked" aria-live="polite">
            <b>이 문항에 쓸 만한 내 기록</b>
            <p className="lp-muted">{active}번 · {topics[active - 1]}</p>
            {records.length === 0 ? (
              <p className="lp-empty">아직 이 문항에 연결한 기록이 없어요. 일지를 쓰며 이 문항을 체크하면 여기에 모입니다.</p>
            ) : records.map((r) => (
              <div key={r.title} className="lp-picked-item">
                <div className="lp-card-head">
                  <span className={kindClass(r.kind)}>{r.kind}</span>
                  <span className="lp-muted">{r.date}</span>
                </div>
                <b>{r.title}</b>
                <p>{r.text}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function FeatureSection() {
  const feats = [
    ["선생님께 제출", "작성한 일지를 담임·교과 선생님께 바로 제출할 수 있어요. 제출 기능은 무료입니다."],
    ["링크로 공유", "상담이나 진로 지도가 필요할 때 링크 하나로 기록을 보여 줄 수 있습니다."],
    ["맞춤법 살펴보기", "저장 전에 맞춤법을 확인해 자기소개서에 옮겨도 깔끔한 문장을 만듭니다."],
  ];
  return (
    <section className="lp-section lp-white" aria-label="그 밖의 기능">
      <div className="wrap lp-feats">
        {feats.map(([t, d]) => (
          <div key={t} className="lp-reveal"><b>{t}</b><p>{d}</p></div>
        ))}
      </div>
    </section>
  );
}

function CTASection() {
  return (
    <section className="lp-section lp-cta" aria-labelledby="lp-cta">
      <div className="wrap">
        <h2 id="lp-cta" className="lp-h2">3분이면 오늘의 기록 하나</h2>
        <p className="lp-muted">졸업할 즈음엔 수많은 경험이 자기소개서와 면접을 기다리고 있을 거예요.</p>
        <div className="lp-cta-row center">
          <Link className="btn btn-primary lp-btn" to="/journals/new?kind=lesson">수업일지 쓰기</Link>
          <Link className="btn lp-btn" to="/journals/new?kind=diary">학교생활일지 쓰기</Link>
        </div>
      </div>
    </section>
  );
}
