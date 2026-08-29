#!/usr/bin/env python3
"""Plot FlexGroup multi-file balance convergence: file count vs aggr1/aggr2 distribution %."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

files   = [100, 300, 500]
aggr1   = [56.4, 55.3, 55.0]
aggr2   = [43.6, 44.7, 45.0]
STRUCT_A1 = 55.6  # 5 constituents / 9
STRUCT_A2 = 44.4  # 4 constituents / 9

fig, ax = plt.subplots(figsize=(10,6))
ax.plot(files, aggr1, 'o-', color='#0067C5', lw=2.5, ms=9, label='aggr1 (5 constituents)')
ax.plot(files, aggr2, 's-', color='#F58220', lw=2.5, ms=9, label='aggr2 (4 constituents)')
ax.axhline(50, color='#5A6B82', ls=':', lw=1.5, label='ideal 50:50')
ax.axhline(STRUCT_A1, color='#2E9E5B', ls='--', lw=1.5, label='structural floor 55.6:44.4 (5:4 constituents)')
ax.axhline(STRUCT_A2, color='#2E9E5B', ls='--', lw=1.5)

for x,y in zip(files, aggr1):
    ax.annotate(f'{y:.1f}%', (x,y), textcoords='offset points', xytext=(0,10), ha='center', color='#0067C5', fontweight='bold')
for x,y in zip(files, aggr2):
    ax.annotate(f'{y:.1f}%', (x,y), textcoords='offset points', xytext=(0,-16), ha='center', color='#F58220', fontweight='bold')

ax.set_xlabel('Number of 1 GiB files written', fontsize=12)
ax.set_ylabel('Share of data per aggregate (%)', fontsize=12)
ax.set_title('FSxN FlexGroup — Multi-file distribution convergence\n(fs-0cd1...757, 9 constituents across aggr1:5 / aggr2:4)', fontsize=13, fontweight='bold')
ax.set_ylim(40, 60)
ax.set_xticks(files)
ax.grid(True, alpha=0.3)
ax.legend(loc='center right', fontsize=10)

# annotation box
txt = ("Prior tests (few large files):\n"
       "  8 files → ~25:75   |   5 files → 40:60\n"
       "This test converges to structural floor by 100 files.\n"
       "Residual skew is STRUCTURAL (5 vs 4 constituents),\n"
       "NOT hash randomness.")
ax.text(0.02, 0.03, txt, transform=ax.transAxes, fontsize=9,
        bbox=dict(boxstyle='round', fc='#F2F6FB', ec='#0067C5', alpha=0.9), va='bottom')

plt.tight_layout()
plt.savefig('flexgroup_balance_convergence.png', dpi=130)
print('saved flexgroup_balance_convergence.png')
