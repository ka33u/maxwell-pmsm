"""Render a two-motor A3 comparison from an audited JSON snapshot. Dimensions are mm."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import numpy as np

W, H = 420, 297
INK, MUTED, RULE = "#122e3a", "#486575", "#cddade"
TEAL, ORANGE = "#006b70", "#aa5129"


def label(fig, x, y, value, size=9, color=INK, bold=False, align="left", **kwargs):
    return fig.text(x/W, 1-y/H, value, fontsize=size, color=color, ha=align, va="center",
                    fontweight="bold" if bold else "normal", **kwargs)


def line(fig, x1, y1, x2, y2, color=RULE, width=.6):
    fig.add_artist(Line2D([x1/W,x2/W],[1-y1/H,1-y2/H],transform=fig.transFigure,
                          color=color,lw=width))


def strip(fig, x, y, width, height, color):
    fig.add_artist(Rectangle((x/W,1-(y+height)/H),width/W,height/H,
                             transform=fig.transFigure,facecolor=color,edgecolor="none",zorder=0))


def section(fig, x, y, title, note, right):
    label(fig,x,y,title,14,bold=True)
    label(fig,right,y,note,8,MUTED,align="right")
    line(fig,x,y+4,right,y+4,TEAL,1)


def table(fig, x, y, width, columns, rows, stops, step=6.3, total=False):
    strip(fig,x,y-2.8,width,5.8,"#e9f2f2")
    for i,row in enumerate([columns]+rows):
        if len(row)!=len(stops):
            raise ValueError("Table column count mismatch")
        is_total=total and i==len(rows)
        if is_total:
            strip(fig,x,y+i*step-step/2,width,step,"#e9f2f2")
        for j,(text,pos) in enumerate(zip(row,stops)):
            label(fig,x+width*pos,y+i*step,str(text),8.5 if i else 8,
                  TEAL if i==0 or is_total else INK,bold=(i==0 or is_total),align="left" if j==0 else "right")
        if i:
            line(fig,x,y+i*step+step/2,x+width,y+i*step+step/2,width=.35)


def axes_mm(fig,x,y,w,h):
    return fig.add_axes([x/W,1-(y+h)/H,w/W,h/H])


def draw_slot(ax, geom, color, scale):
    p,g=geom["inputs"],geom["slot_geometry"]
    ri=g["bore_radius"]
    def local(name):
        x,y=g[name]
        return x,y-ri
    right=[local(k) for k in ("mouth_right","mouth_depth_right","shoulder_right","tangent_right")]
    cx,cy=local("bottom_center")
    radius=g["bottom_radius"]
    arc=np.deg2rad(np.linspace(g["bottom_arc_start_deg"],g["bottom_arc_end_deg"],91))
    rim=right+list(zip(cx+radius*np.cos(arc),cy+radius*np.sin(arc)))+[(-x,y) for x,y in reversed(right)]
    x,y=zip(*rim)
    ax.fill(x,y,color=color,alpha=.09)
    ax.plot(x,y,color=color,lw=1.65)
    for side in (-1,1):
        bx=side*np.linspace(p["b0"]/2,min(ri*.95,7.6*scale),30)
        ax.plot(bx,np.sqrt(ri**2-bx**2)-ri,color=color,lw=1.1)
    ax.plot([0,0],[-1.2*scale,cy+radius+1.1*scale],lw=.55,color=MUTED,ls="-.")
    def call(point, end, text, align="left"):
        ax.annotate(text,xy=point,xytext=end,ha=align,va="center",size=8,color=INK,
                    arrowprops=dict(arrowstyle="-",color=MUTED,lw=.65,shrinkA=1,shrinkB=1))
    def height(xdim,y0,y1,text,edge):
        ax.plot([edge,xdim],[y0,y0],color=MUTED,lw=.5)
        ax.plot([edge,xdim],[y1,y1],color=MUTED,lw=.5)
        ax.annotate("",xy=(xdim,y0),xytext=(xdim,y1),
                    arrowprops=dict(arrowstyle="<->",lw=.55,mutation_scale=6,color=MUTED))
        ax.text(xdim-.65*scale,(y0+y1)/2,text,rotation=90,ha="right",va="center",size=8,color=INK)
    height(-12.8*scale,0,g["slot_depth"],"槽深 %g"%g["slot_depth"],0)
    height(-8.6*scale,p["h0"],cy,"hs12 %g"%p["hs12"],-p["b0"]/2)
    call((radius*.70,cy+radius*.714),(8.1*scale,cy+radius*.76),"R %g"%radius)
    call(right[2],(7.7*scale,13.1*scale),"肩宽 bs1 %g"%p["b1"])
    call(((right[1][0]+right[2][0])/2,(right[1][1]+right[2][1])/2),(7.7*scale,8.4*scale),"槽肩 %g°"%p["shoulder_deg"])
    call(right[1],(7.7*scale,3.8*scale),"口深 hs0 %g"%p["h0"])
    call(right[0],(5.2*scale,-3.0*scale),"口宽 b01 %g"%p["b0"])
    ax.set(xlim=(-16*scale,20*scale),ylim=(-5*scale,37*scale),aspect="equal")
    ax.axis("off")


def render(data, out, font=None):
    if font:
        font_manager.fontManager.addfont(font)
        family=font_manager.FontProperties(fname=font).get_name()
    else:
        family="Microsoft YaHei"
    plt.rcParams.update({"font.family":family,"pdf.fonttype":42,"axes.unicode_minus":False})
    motors=data["motors"]
    if len(motors)!=2:
        raise ValueError("This comparison layout requires two motors")
    fig=plt.figure(figsize=(W/25.4,H/25.4),facecolor="white")
    strip(fig,0,0,W,29,"#153742")
    label(fig,10,10,data["title"],22,"white",True)
    label(fig,10,21,data["subtitle"],10,"#dcf0ec")
    label(fig,410,10,data["date"],11,"white",align="right")
    label(fig,410,21,data["version"],9,"#dcf0ec",align="right")
    section(fig,10,38,"局部槽型与标注尺寸","定子单槽截面  /  mm",196)
    section(fig,205,38,"空载与带载磁密","末电周期  /  T",410)
    # Same physical scale for both slots, with space for callouts around the larger section.
    scale=max(max(m["geometry"]["slot_geometry"]["slot_depth"]/34,
                  m["geometry"]["slot_geometry"]["bottom_radius"]/5.3,
                  m["geometry"]["inputs"]["b1"]/8.3) for m in motors)
    for i,(motor,color) in enumerate(zip(motors,[TEAL,ORANGE])):
        x=10+i*95
        label(fig,x+1,49,motor["name"],12,color,True)
        draw_slot(axes_mm(fig,x+3,52,87,78),motor["geometry"],color,scale)
        for k,s in enumerate(motor["dimensions"]):
            label(fig,x+1,134+5.4*k,s,8.1,INK)
    line(fig,102.5,48,102.5,158,width=.4)
    table(fig,205,49,205,data["flux_headers"],data["flux_rows"],[.012,.49,.65,.815,.985],5.65)
    label(fig,206,111,data["wave_title"],8.6,INK,True)
    ax=axes_mm(fig,217,117,187,32)
    for m,c in zip(motors,[TEAL,ORANGE]):
        angles,field=zip(*m["gap_wave"])
        ax.plot(angles,field,color=c,lw=1.4,label=m["short"])
    ax.set_xlim(min(min(s[0] for s in m["gap_wave"]) for m in motors),
                max(max(s[0] for s in m["gap_wave"]) for m in motors))
    ax.tick_params(labelsize=7,length=2,color=RULE)
    ax.grid(axis="y",alpha=.20)
    ax.spines[["top","right"]].set_visible(False)
    ax.spines[["bottom","left"]].set_color(RULE)
    ax.legend(loc="upper right",ncols=2,fontsize=7,frameon=False)
    label(fig,407,158,"机械角 / °",8,MUTED,align="right")
    line(fig,10,163,410,163,width=.8)
    section(fig,10,172,"反电势、转矩与损耗",f'{data["speed_rpm"]:g} r/min',196)
    section(fig,205,172,"单台主要材料成本","设计净用量  /  人民币",410)
    table(fig,10,183,186,data["performance_headers"],data["performance_rows"],[.012,.69,.985],6.3)
    table(fig,205,183,205,data["cost_headers"],data["cost_rows"],[.012,.40,.695,.985],7.6,total=True)
    if "winding_rows" in data:
        if len(data["winding_rows"]) > 6 or len(data["limits"]) > 5:
            raise ValueError("Comparison winding layout supports six rows and five scope notes")
        for j,s in enumerate(data["price_notes"]):
            label(fig,206,219+j*4.4,s,8,MUTED)
        section(fig,205,235,"绕组、负荷与电感",data["winding_note"],410)
        table(fig,205,244,205,data["performance_headers"],data["winding_rows"],[.012,.69,.985],5)
        strip(fig,0,278,W,19,"#e9f2f2")
        for j,s in enumerate([*data["limits"],data["winding_basis"]]):
            label(fig,10+198*(j//3),281+4.2*(j%3),s,8,INK)
        for j,s in enumerate(data["footer"]):
            label(fig,10+198*j,294,s,7.3,TEAL)
    else:
        for j,s in enumerate(data["price_notes"]):
            label(fig,206,224+j*5.2,s,8,MUTED)
        label(fig,205,245,"计算条件与适用范围",11,INK,True)
        for j,s in enumerate(data["limits"]):
            label(fig,206,253+j*5.1,s,8.2,INK)
        strip(fig,0,282,W,15,"#e9f2f2")
        label(fig,10,287,data["footer"][0],8.5,TEAL,True)
        label(fig,10,293,data["footer"][1],8,MUTED)
    out.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(out.with_suffix(".pdf"),format="pdf")
    fig.savefig(out.with_suffix(".png"),dpi=210)
    plt.close(fig)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data",type=Path)
    parser.add_argument("out",type=Path,help="PDF/PNG base path")
    parser.add_argument("--font",help="CJK font file if the default is unavailable")
    args=parser.parse_args()
    render(json.loads(args.data.read_text(encoding="utf-8-sig")),args.out,args.font)
