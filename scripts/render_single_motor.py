"""Render a single PMSM operating report from a portable, per-motor JSON snapshot."""
import argparse
import json
from pathlib import Path

import numpy as np
from matplotlib import font_manager
from matplotlib.patches import Polygon, Rectangle

from render_motor_sheet import (H, W, INK, MUTED, ORANGE, RULE, TEAL, axes_mm, draw_slot,
                               label, line, plt, section, strip, table)

STEEL = "#d7e5e7"
MAGNET = "#e8a46e"
PHASES = [TEAL, ORANGE, "#5368a2"]


def pole_detail(ax, geom, poles):
    """Stationary top pole aligned with slot 1. All parts share model coordinates."""
    g, p = geom["slot_geometry"], geom["inputs"]
    bore = g["bore_radius"]
    half_pitch = 180 / poles
    deg = np.linspace(-half_pitch, half_pitch, round(2*half_pitch)+1)
    a = np.deg2rad(deg)
    d, r = geom["pole_arc_center_offset"], geom["pole_arc_radius"]
    radial = d*np.cos(a) + np.sqrt(r**2-(d*np.sin(a))**2)
    x, y = radial*np.sin(a), radial*np.cos(a)
    lower = geom["pocket_y0"]-3
    ax.fill_between(x, lower, y, color=STEEL,edgecolor=MUTED,lw=.7)
    # The stator band is cut off above the slot bottoms to expose the local cross-section.
    outer = g["bottom_outer_radius"]+2.2
    angles = np.linspace(-np.deg2rad(half_pitch),np.deg2rad(half_pitch),150)
    bound = np.column_stack([np.r_[bore*np.sin(angles),outer*np.sin(angles[::-1])],
                             np.r_[bore*np.cos(angles),outer*np.cos(angles[::-1])]])
    stator = Polygon(bound,closed=True,facecolor=STEEL,edgecolor="none")
    ax.add_patch(stator)
    ax.plot(outer*np.sin(angles),outer*np.cos(angles),color=MUTED,lw=.7)
    for end in angles[[0,-1]]:
        ax.plot(np.array([bore,outer])*np.sin(end),np.array([bore,outer])*np.cos(end),color=MUTED,lw=.7)
    pitch=2*np.pi/p["slots"]
    mouth_half=np.arcsin(p["b0"]/(2*bore))
    slot_indices=range(-int(np.ceil(p["slots"]/(2*poles))),int(np.ceil(p["slots"]/(2*poles)))+1)
    for index in slot_indices:
        start=max(angles[0],index*pitch+mouth_half)
        stop=min(angles[-1],(index+1)*pitch-mouth_half)
        if start<stop:
            arc_angles=np.linspace(start,stop,20)
            ax.plot(bore*np.sin(arc_angles),bore*np.cos(arc_angles),color=MUTED,lw=.7)
    arc = np.deg2rad(np.linspace(g["bottom_arc_start_deg"],g["bottom_arc_end_deg"],40))
    sx = np.array([g["mouth_right"],g["mouth_depth_right"],g["shoulder_right"]])
    bottom = np.column_stack([g["bottom_radius"]*np.cos(arc),
                              g["bottom_center"][1]+g["bottom_radius"]*np.sin(arc)])
    mirrored=sx[::-1]*[-1,1]
    slot=np.vstack([sx,bottom,mirrored])
    for index in slot_indices:
        phi=np.deg2rad(360*index/p["slots"])
        rotation=np.array([[np.cos(phi),np.sin(phi)],[-np.sin(phi),np.cos(phi)]])
        transformed=slot@rotation
        shape=Polygon(transformed,closed=True,facecolor="white",edgecolor="none")
        ax.add_patch(shape)
        shape.set_clip_path(stator)
        outline,=ax.plot(*transformed.T,color=TEAL,lw=.55)
        outline.set_clip_path(stator)
    for sign in (-1,1):
        for prefix,fill,edge in [("pocket","white",INK),("magnet",MAGNET,ORANGE)]:
            x0,x1=geom[prefix+"_x0"],geom[prefix+"_x1"]
            y0,y1=geom[prefix+"_y0"],geom[prefix+"_y1"]
            ax.add_patch(Rectangle((x0 if sign==1 else -x1,y0),x1-x0,y1-y0,
                                   facecolor=fill,edgecolor=edge,lw=.65))
    ax.annotate("极顶气隙",xy=(5,(bore+geom["rotor_tip_radius"])/2),
                xytext=(x.min()*.55,bore+5),color=INK,fontsize=7.1,
                arrowprops=dict(arrowstyle="-",color=MUTED,lw=.65))
    ax.annotate("中桥",xy=(0,(geom["pocket_y0"]+geom["pocket_y1"])/2),
                xytext=(0,lower-2),ha="center",va="top",color=INK,fontsize=7.1,
                arrowprops=dict(arrowstyle="-",color=MUTED,lw=.65))
    ax.set_aspect("equal")
    span=outer*np.sin(np.deg2rad(half_pitch))
    ax.set_xlim(-span-1,span+1)
    ax.set_ylim(lower-6,outer+1)
    ax.axis("off")


def magnet_view(ax, part):
    b,h,l = (part[key] for key in ("width_mm","thickness_mm","segment_mm"))
    # Parallel projection. Front face is B x H; the receding edges run along the shaft.
    face=np.array([[0.,0.],[b,0.],[b,h],[0.,h]])
    shift=l*np.array([.51,.39])
    for pts,facecolor in [(face,"#efb384"),([face[1],face[1]+shift,face[2]+shift,face[2]],"#c67d50"),
                          ([face[3],face[2],face[2]+shift,face[3]+shift],"#f7cfad")]:
        ax.add_patch(Polygon(pts,facecolor=facecolor,edgecolor=ORANGE,lw=.9))
    ax.text(b/2,-1.0,f'B {b:g}',ha="center",va="top",size=8,color=INK)
    ax.text(b+shift[0]*.50+2,shift[1]*.5-2,f'L {l:g}',size=8,color=INK)
    ax.annotate(f'H {h:g}',xy=(0,h*.5),xytext=(-2,h+3.5),ha="right",fontsize=8,color=INK,
                arrowprops=dict(arrowstyle="-",lw=.6,color=MUTED))
    ax.annotate("",xy=(b*.35,h-.1),xytext=(b*.35,.1),
                arrowprops=dict(arrowstyle="-|>",lw=1.3,color=INK,mutation_scale=9))
    ax.set_aspect("equal")
    ax.set(xlim=(-12,b+shift[0]+6),ylim=(-5,h+shift[1]+2))
    ax.axis("off")


def pocket_end(ax, geom, cad):
    x1=geom["pocket_x1"]
    y0=geom["pocket_y0"]
    y1=geom["pocket_y1"]
    protrusion=cad["end_x_mm"]-x1
    xleft=x1-max(3,protrusion*1.1)
    ax.add_patch(Rectangle((xleft-1,geom["magnet_y0"]),geom["magnet_x1"]-xleft+1,
                           geom["magnet_y1"]-geom["magnet_y0"],facecolor=MAGNET,edgecolor="none"))
    ax.plot([xleft-1,x1,x1,xleft-1],[y0,y0,y1,y1],color=ORANGE,ls="--",lw=1.05,zorder=4)
    for path in cad["paths"]:
        xy=np.array(path)
        ax.plot(xy[:,0],xy[:,1],lw=1.25,color=TEAL)
    ax.set(xlim=(xleft,cad["end_x_mm"]+1.4),ylim=(y0-.8,y1+.8),aspect="equal")
    ax.axis("off")


def plot_wave(fig, x, y, width, wave):
    label(fig,x,y,wave["title"],9.8,bold=True)
    label(fig,x+width,y,wave["x_label"],8,MUTED,align="right")
    ax=axes_mm(fig,x+9,y+6,width-11,22.5)
    ticks=np.array(wave["x"])
    for i,(name,values) in enumerate(wave["series"].items()):
        ax.plot(ticks,values,label=name,color=PHASES[i],lw=1.05,
                marker="o" if wave.get("show_points") else None,markersize=2.2)
    ax.set_xlim(ticks.min(),ticks.max())
    if len(wave["series"])>1:
        ax.legend(loc="upper right",fontsize=6.4,ncols=len(wave["series"]),frameon=True,
                  borderpad=.1,framealpha=.9,handlelength=1.3,handletextpad=.3,columnspacing=.7)
    ax.spines[["top","right"]].set_visible(False)
    ax.spines[["bottom","left"]].set_color(RULE)
    ax.grid(axis="y",alpha=.23)
    ax.tick_params(labelsize=6.8,length=2,pad=1.5,color=MUTED)


def render(data, basename, font=None):
    if font:
        font_manager.fontManager.addfont(font)
    family=font_manager.FontProperties(fname=font).get_name() if font else "Microsoft YaHei"
    plt.rcParams.update({"font.family":family,"pdf.fonttype":42,"axes.unicode_minus":False})
    fig=plt.figure(figsize=(W/25.4,H/25.4),facecolor="white")
    strip(fig,0,0,W,24,"#153742")
    label(fig,10,9,data["name"]+"   永磁同步电机仿真报告",20,"white",True)
    label(fig,10,18.7,data["subtitle"],9.5,"#dcf0ec")
    label(fig,410,9,data["date"],10,"white",align="right")
    label(fig,410,18.7,"Maxwell 2D   /   单机电磁与材料成本",8.5,"#dcf0ec",align="right")
    section(fig,10,32,"定子、转子与磁钢","尺寸 mm  ·  局部截面",270)
    section(fig,280,32,"运行性能与损耗","设计电流下的指定相角",410)
    geom=data["geometry"]; part=data["magnet"]; cad=data["rotor_cad"]
    label(fig,10,43,"定子单槽",10.5,TEAL,True)
    label(fig,81,43,"一极定转子装配截面",10.5,TEAL,True)
    label(fig,201,43,"单块磁钢",10.5,TEAL,True)
    scale=max(geom["slot_geometry"]["slot_depth"]/34,geom["slot_geometry"]["bottom_radius"]/5.3,
              geom["inputs"]["b1"]/8.3)
    draw_slot(axes_mm(fig,10,49,68,62),geom,TEAL,scale)
    pole_detail(axes_mm(fig,81,49,112,62),geom,data["poles"])
    magnet_view(axes_mm(fig,201,47,68,28),part)
    label(fig,201,80,"磁槽外端放大",9.7,TEAL,True)
    pocket_end(axes_mm(fig,202,83,33,25),geom,cad)
    label(fig,239,88,"实线  转子图纸",7.9,TEAL)
    label(fig,239,95,"虚线  求解磁槽",7.9,ORANGE)
    label(fig,239,102,"填色  磁钢",7.9,INK)
    for i,(x,lines) in enumerate(zip([10,81,201],data["geometry_notes"])):
        for j,s in enumerate(lines):
            label(fig,x,115+j*5.6,s,8.0,INK)
    line(fig,78,42,78,131)
    line(fig,196,42,196,131)
    table(fig,280,44,130,["项目","结果"],data["performance"],[.012,.984],5.2)
    section(fig,280,124,"气隙、齿身与轭部磁密","末电周期  /  T",410)
    table(fig,280,135,130,["磁密指标","空载","带载"],data["flux"],[.012,.735,.985],5.55)
    section(fig,280,202,"主要材料净成本","人民币  /  台",410)
    table(fig,280,213,130,["项目","净重 kg","元/kg","金额 元"],data["costs"],[.012,.52,.72,.985],6.4,total=True)
    for j,s in enumerate(data["cost_notes"]):
        label(fig,281,247+j*5,s,7.8,MUTED)
    section(fig,10,141,"电磁波形","时间轴为求解时刻，空间波形为全局机械角",270)
    if len(data["waves"])!=6:
        raise ValueError("Six waveform panels are required")
    if "winding_rows" in data:
        if len(data["winding_rows"]) > 6:
            raise ValueError("Single-sheet winding table supports six rows")
        for i,wave in enumerate(data["waves"]):
            plot_wave(fig,10+88*(i%3),153+39*(i//3),83,wave)
        section(fig,10,232,"绕组、负荷与电感",data["winding_note"],270)
        details = data.get("winding_details", [])
        if len(details) > 5:
            raise ValueError("Single-sheet winding layout supports five detail lines")
        table(fig,10,243,140,["指标","数值"],data["winding_rows"],[.012,.985],5.2)
        label(fig,157,243,"额定工况与数据口径",9,TEAL,True)
        for j,note in enumerate(details):
            label(fig,157,250+5.6*j,note,8.2)
        if not details:
            label(fig,11,279,data["winding_basis"],8,MUTED)
    else:
        for i,wave in enumerate(data["waves"]):
            plot_wave(fig,[10,144][i%2],154+43*(i//2),126,wave)
    line(fig,275,31,275,278)
    strip(fig,0,283,W,14,"#e9f2f2")
    for j,s in enumerate(data["footnotes"]):
        label(fig,10,287+j*5.4,s,8.1,TEAL if j==0 else MUTED,bold=(j==0))
    basename.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(basename.with_suffix(".pdf"))
    fig.savefig(basename.with_suffix(".png"),dpi=210)
    plt.close(fig)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("--font")
    args=parser.parse_args()
    render(json.loads(args.data.read_text(encoding="utf-8-sig")),args.output,args.font)
