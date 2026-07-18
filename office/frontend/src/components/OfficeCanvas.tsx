import { useEffect, useRef } from "react";
import { Application, Container, Graphics, Text } from "pixi.js";
import type { ProposalDecision, WeekPayload } from "../types";
import { decisionsById, verdictClass, verdictLabel } from "../lib/format";

type Props = {
  week?: WeekPayload;
  statusMessage: string;
};

type DeptPosition = {
  x: number;
  y: number;
  label: string;
  color: number;
  avatarX: number;
  avatarY: number;
};

const DEPT_POSITIONS: Record<string, DeptPosition> = {
  supply_chain: { x: 86, y: 116, label: "Supply", color: 0x2563eb, avatarX: 255, avatarY: 148 },
  finance: { x: 818, y: 116, label: "Finance", color: 0xf59e0b, avatarX: 770, avatarY: 148 },
  store_ops: { x: 86, y: 404, label: "Ops", color: 0x16a34a, avatarX: 255, avatarY: 436 },
  growth: { x: 818, y: 404, label: "Growth", color: 0xec4899, avatarX: 770, avatarY: 436 },
};

const VERDICT_COLORS: Record<string, number> = {
  approve: 0x22c55e,
  reject: 0xef4444,
  flag: 0xfacc15,
  modify: 0x38bdf8,
  info: 0x94a3b8,
  pending: 0x6b7280,
};

export function OfficeCanvas({ week, statusMessage }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const appRef = useRef<Application | null>(null);

  useEffect(() => {
    let cancelled = false;
    const app = new Application();
    appRef.current = app;

    async function init() {
      await app.init({
        width: 1100,
        height: 640,
        backgroundColor: 0x111827,
        antialias: false,
        autoDensity: true,
        resolution: window.devicePixelRatio || 1,
      });
      if (cancelled || !hostRef.current) {
        app.destroy();
        return;
      }
      hostRef.current.appendChild(app.canvas);
      drawOffice(app, week, statusMessage);
    }

    init();
    return () => {
      cancelled = true;
      app.destroy(true);
      appRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (appRef.current) {
      drawOffice(appRef.current, week, statusMessage);
    }
  }, [week, statusMessage]);

  return <div className="office-canvas pixel-border" ref={hostRef} />;
}

function drawOffice(app: Application, week: WeekPayload | undefined, statusMessage: string) {
  app.stage.removeChildren();
  const stage = app.stage;

  drawRoom(stage);
  drawTitle(stage, week);
  drawDepartments(stage);
  drawCeo(stage, statusMessage);
  drawProposalCards(stage, week);
  drawStatusBins(stage);
}

function drawRoom(stage: Container) {
  stage.addChild(new Graphics().rect(34, 60, 1032, 198).fill(0x334155));
  const floor = new Graphics()
    .rect(34, 246, 1032, 334)
    .fill(0x1f2937)
    .stroke({ color: 0x475569, width: 4 });
  stage.addChild(floor);

  stage.addChild(new Graphics().rect(34, 234, 1032, 18).fill(0x0f172a));
  stage.addChild(new Graphics().rect(414, 356, 272, 124).fill(0x7f1d1d).stroke({ color: 0xfacc15, width: 3 }));
  for (let y = 372; y < 466; y += 22) {
    stage.addChild(new Graphics().rect(430, y, 240, 5).fill(0x991b1b));
  }

  for (let x = 58; x < 1044; x += 46) {
    stage.addChild(new Graphics().rect(x, 548, 24, 8).fill(0x374151));
  }

  drawWindow(stage, 72, 86);
  drawWindow(stage, 852, 86);
  drawShelf(stage, 84, 276);
  drawPlant(stage, 976, 310);
  drawWaterCooler(stage, 916, 396);
  drawWallClock(stage, 714, 118);

  stage.addChild(new Graphics().rect(446, 84, 208, 70).fill(0x0f172a).stroke({ color: 0x64748b, width: 3 }));
  addText(stage, "KPI WAR ROOM", 485, 106, 17, 0xe2e8f0);
  stage.addChild(new Graphics().rect(476, 132, 148, 8).fill(0x22c55e));
}

function drawWindow(stage: Container, x: number, y: number) {
  stage.addChild(new Graphics().rect(x, y, 158, 98).fill(0x0ea5e9).stroke({ color: 0xe2e8f0, width: 4 }));
  stage.addChild(new Graphics().rect(x + 74, y + 4, 8, 90).fill(0xe2e8f0));
  stage.addChild(new Graphics().rect(x + 4, y + 46, 150, 8).fill(0xe2e8f0));
  stage.addChild(new Graphics().rect(x + 14, y + 64, 28, 30).fill(0x1e293b));
  stage.addChild(new Graphics().rect(x + 48, y + 50, 36, 44).fill(0x334155));
  stage.addChild(new Graphics().rect(x + 98, y + 58, 42, 36).fill(0x1e293b));
}

function drawShelf(stage: Container, x: number, y: number) {
  stage.addChild(new Graphics().rect(x, y, 128, 92).fill(0x78350f).stroke({ color: 0x451a03, width: 3 }));
  for (let shelfY = y + 18; shelfY < y + 82; shelfY += 24) {
    stage.addChild(new Graphics().rect(x + 8, shelfY, 112, 5).fill(0xfbbf24));
    stage.addChild(new Graphics().rect(x + 16, shelfY - 14, 12, 14).fill(0x2563eb));
    stage.addChild(new Graphics().rect(x + 34, shelfY - 14, 12, 14).fill(0xef4444));
    stage.addChild(new Graphics().rect(x + 52, shelfY - 14, 12, 14).fill(0x22c55e));
  }
}

function drawPlant(stage: Container, x: number, y: number) {
  stage.addChild(new Graphics().rect(x - 18, y + 58, 36, 34).fill(0x92400e).stroke({ color: 0x451a03, width: 3 }));
  stage.addChild(new Graphics().rect(x - 4, y + 22, 8, 46).fill(0x166534));
  stage.addChild(new Graphics().rect(x - 36, y + 12, 34, 18).fill(0x22c55e));
  stage.addChild(new Graphics().rect(x + 4, y + 4, 38, 18).fill(0x16a34a));
  stage.addChild(new Graphics().rect(x - 28, y + 34, 30, 18).fill(0x15803d));
  stage.addChild(new Graphics().rect(x + 6, y + 34, 30, 18).fill(0x22c55e));
}

function drawWaterCooler(stage: Container, x: number, y: number) {
  stage.addChild(new Graphics().rect(x, y, 42, 70).fill(0xe2e8f0).stroke({ color: 0x0f172a, width: 3 }));
  stage.addChild(new Graphics().rect(x + 7, y - 28, 28, 30).fill(0x38bdf8).stroke({ color: 0x0f172a, width: 3 }));
  stage.addChild(new Graphics().rect(x + 12, y + 20, 18, 8).fill(0x0f172a));
}

function drawWallClock(stage: Container, x: number, y: number) {
  stage.addChild(new Graphics().circle(x, y, 28).fill(0xf8fafc).stroke({ color: 0x0f172a, width: 4 }));
  stage.addChild(new Graphics().rect(x - 2, y - 18, 4, 20).fill(0x0f172a));
  stage.addChild(new Graphics().rect(x, y - 2, 14, 4).fill(0x0f172a));
}

function drawTitle(stage: Container, week?: WeekPayload) {
  addText(stage, "RETAIL CEO OFFICE", 38, 20, 23, 0xfacc15);
  addText(stage, `Week ${week?.week ?? "-"} live operations`, 860, 24, 14, 0xcbd5e1);
}

function drawDepartments(stage: Container) {
  Object.values(DEPT_POSITIONS).forEach((dept) => {
    stage.addChild(new Graphics().rect(dept.x, dept.y, 178, 94).fill(0x0f172a).stroke({ color: dept.color, width: 4 }));
    addText(stage, dept.label, dept.x + 20, dept.y + 12, 16, 0xffffff);
    stage.addChild(new Graphics().rect(dept.x + 20, dept.y + 54, 126, 16).fill(dept.color));
    drawFigurine(stage, {
      x: dept.avatarX,
      y: dept.avatarY,
      scale: 0.7,
      shirt: dept.color,
      label: dept.label.slice(0, 3).toUpperCase(),
    });
  });
}

function drawCeo(stage: Container, statusMessage: string) {
  stage.addChild(new Graphics().rect(448, 266, 204, 110).fill(0x78350f).stroke({ color: 0xfacc15, width: 4 }));
  drawFigurine(stage, {
    x: 550,
    y: 252,
    scale: 1.35,
    shirt: 0x2563eb,
    label: "CEO",
    crown: true,
  });
  stage.addChild(new Graphics().roundRect(356, 410, 388, 64, 8).fill(0xf8fafc).stroke({ color: 0x0f172a, width: 3 }));
  addText(stage, statusMessage.slice(0, 54), 378, 430, 13, 0x0f172a);
}

function drawProposalCards(stage: Container, week?: WeekPayload) {
  const decisions = decisionsById(week?.decisions);
  const deptCounts: Record<string, number> = {};

  (week?.inbox ?? []).forEach((proposal) => {
    const dept = DEPT_POSITIONS[proposal.dept] ?? DEPT_POSITIONS.supply_chain;
    const index = deptCounts[proposal.dept] ?? 0;
    deptCounts[proposal.dept] = index + 1;
    const decision = decisions[proposal.proposal_id];
    const progress = decision ? 1 : 0.18 + Math.min(index, 4) * 0.08;
    const startX = dept.avatarX + (dept.avatarX < 550 ? 42 : -102);
    const startY = dept.avatarY - 18 + index * 15;
    const end = verdictDestination(decision);
    const x = startX + (end.x - startX) * progress;
    const y = startY + (end.y - startY) * progress;
    const cls = verdictClass(decision?.verdict);
    const color = VERDICT_COLORS[cls] ?? VERDICT_COLORS.pending;

    stage.addChild(new Graphics().rect(x, y, 70, 24).fill(0xf8fafc).stroke({ color, width: 3 }));
    addText(stage, proposal.proposal_id, x + 7, y + 6, 10, 0x111827);
  });
}

function drawStatusBins(stage: Container) {
  const bins = [
    { label: "APPROVE", x: 410, y: 522, color: VERDICT_COLORS.approve },
    { label: "REJECT", x: 514, y: 522, color: VERDICT_COLORS.reject },
    { label: "INFO", x: 608, y: 522, color: VERDICT_COLORS.info },
  ];
  bins.forEach((bin) => {
    stage.addChild(new Graphics().rect(bin.x, bin.y, 84, 34).fill(0x0f172a).stroke({ color: bin.color, width: 3 }));
    addText(stage, bin.label, bin.x + 13, bin.y + 10, 11, 0xffffff);
  });
}

function verdictDestination(decision?: ProposalDecision) {
  const label = verdictLabel(decision?.verdict);
  if (label === "approve") return { x: 416, y: 488 };
  if (label === "reject") return { x: 520, y: 488 };
  if (label === "request info") return { x: 614, y: 488 };
  return { x: 515, y: 358 };
}

function drawFigurine(
  stage: Container,
  {
    x,
    y,
    scale,
    shirt,
    label,
    crown = false,
  }: { x: number; y: number; scale: number; shirt: number; label: string; crown?: boolean },
) {
  const skin = 0xfbbf24;
  const outline = 0x111827;
  const px = (value: number) => value * scale;
  const left = x - px(18);
  const top = y - px(42);

  if (crown) {
    stage.addChild(new Graphics().rect(x - px(14), top - px(10), px(28), px(8)).fill(0xfacc15).stroke({ color: outline, width: px(2) }));
    stage.addChild(new Graphics().rect(x - px(10), top - px(18), px(6), px(10)).fill(0xfacc15));
    stage.addChild(new Graphics().rect(x - px(2), top - px(22), px(6), px(14)).fill(0xfacc15));
    stage.addChild(new Graphics().rect(x + px(6), top - px(18), px(6), px(10)).fill(0xfacc15));
  }

  stage.addChild(new Graphics().rect(left, top, px(36), px(34)).fill(skin).stroke({ color: outline, width: px(2) }));
  stage.addChild(new Graphics().rect(left + px(7), top + px(13), px(6), px(6)).fill(outline));
  stage.addChild(new Graphics().rect(left + px(23), top + px(13), px(6), px(6)).fill(outline));
  stage.addChild(new Graphics().rect(left + px(12), top + px(25), px(12), px(4)).fill(0x7c2d12));

  stage.addChild(new Graphics().rect(x - px(22), y - px(6), px(44), px(48)).fill(shirt).stroke({ color: outline, width: px(2) }));
  stage.addChild(new Graphics().rect(x - px(36), y + px(2), px(14), px(32)).fill(skin).stroke({ color: outline, width: px(2) }));
  stage.addChild(new Graphics().rect(x + px(22), y + px(2), px(14), px(32)).fill(skin).stroke({ color: outline, width: px(2) }));
  stage.addChild(new Graphics().rect(x - px(18), y + px(42), px(14), px(34)).fill(0x0f172a).stroke({ color: outline, width: px(2) }));
  stage.addChild(new Graphics().rect(x + px(4), y + px(42), px(14), px(34)).fill(0x0f172a).stroke({ color: outline, width: px(2) }));
  stage.addChild(new Graphics().rect(x - px(24), y + px(74), px(22), px(8)).fill(0x334155));
  stage.addChild(new Graphics().rect(x + px(4), y + px(74), px(22), px(8)).fill(0x334155));
  addText(stage, label, x - px(15), y + px(11), Math.max(9, px(11)), 0xffffff);
}

function addText(stage: Container, text: string, x: number, y: number, size: number, fill: number) {
  const node = new Text({
    text,
    style: {
      fill,
      fontFamily: "monospace",
      fontSize: size,
      fontWeight: "700",
    },
  });
  node.x = x;
  node.y = y;
  stage.addChild(node);
}

