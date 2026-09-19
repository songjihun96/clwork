import { useEffect } from "react";
import { MapContainer, Marker, Popup, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";   // 지도를 열 때만 함께 내려받는다

// 번들러가 기본 마커 이미지를 못 찾는 문제를 피하려고 직접 그린 마커를 쓴다.
// 핀 색은 '학교 계열'을 나타낸다. 유료 등급은 반영하지 않는다.
// 등급별로 색을 달리하면 지도 자체가 광고 표시처럼 읽히고, 학교 카드에서
// 등급을 감춘 정책과도 어긋난다. 계열은 이용자에게 실제로 쓸모 있는 정보다.
const CATEGORY_COLOR = {
  "특성화고": "#ff7a59",
  "마이스터고": "#d5330e",
  "종합고": "#c2691a",
  "특목고": "#7b5ea7",
  "과학고": "#2f7fd4",
  "외국어고": "#1d9e75",
  "국제고": "#0f8a8a",
  "예술고": "#d4537e",
  "체육고": "#ba7517",
  "자율고": "#645d69",
  "일반고": "#888780",
};
const FALLBACK_COLOR = "#ff9166";

function colorOf(category) {
  return CATEGORY_COLOR[category] || FALLBACK_COLOR;
}

function pinIcon(category) {
  const color = colorOf(category);
  const stroke = "#ffffff";   // 밝은 지도 위에서 핀 윤곽이 또렷하도록
  return L.divIcon({
    className: "",
    html: `<svg width="26" height="33" viewBox="-1 -1 26 33" xmlns="http://www.w3.org/2000/svg">
      <path d="M12 0C5.4 0 0 5.3 0 11.8 0 20.6 12 30 12 30s12-9.4 12-18.2C24 5.3 18.6 0 12 0z"
        fill="${color}" stroke="${stroke}" stroke-width="1.8"
        style="filter: drop-shadow(0 1px 2px rgba(45,42,50,.35))"/>
      <circle cx="12" cy="11.5" r="4.2" fill="${stroke}"/>
    </svg>`,
    iconSize: [26, 33],
    iconAnchor: [13, 31],
    popupAnchor: [0, -29],
  });
}

function FitBounds({ items }) {
  const map = useMap();
  useEffect(() => {
    if (items.length === 0) return;
    if (items.length === 1) {
      // 한 곳만 남으면 경계 계산이 의미가 없으므로 그 지점을 충분히 확대한다.
      map.setView([items[0].latitude, items[0].longitude], 15);
      return;
    }
    const bounds = L.latLngBounds(items.map((s) => [s.latitude, s.longitude]));
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
  }, [items, map]);
  return null;
}

export default function MapView({ items, onOpen }) {
  if (items.length === 0) {
    return (
      <div className="empty">
        <h3>지도에 표시할 학교가 없습니다</h3>
        <p>검색 조건을 바꾸거나, 목록 보기로 확인해보세요.</p>
      </div>
    );
  }

  // 지금 지도에 실제로 찍힌 계열만 범례에 보여준다.
  const legend = [];
  for (const it of items) {
    if (it.category && !legend.includes(it.category)) legend.push(it.category);
  }

  return (
    <div className="map-box">
      {legend.length > 1 && (
        <div className="map-legend">
          {legend.map((c) => (
            <span key={c}>
              <i style={{ background: colorOf(c) }} />
              {c}
            </span>
          ))}
        </div>
      )}
      <MapContainer center={[36.5, 127.8]} zoom={7} style={{ height: "100%", width: "100%" }}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds items={items} />
        {items.map((s) => (
          <Marker key={s.id} position={[s.latitude, s.longitude]} icon={pinIcon(s.category)}>
            <Popup>
              <div style={{ minWidth: 170 }}>
                <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 3 }}>{s.name}</div>
                <div style={{ fontSize: 12, color: "#5d6e7e", marginBottom: 7 }}>
                  {s.category} · {s.coed}
                  {s.dormitory === true && " · 기숙사"}
                  <br />
                  {s.address}
                </div>
                <button className="btn btn-sm" onClick={() => onOpen(s.id)} style={{ width: "100%" }}>
                  상세 보기
                </button>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}
