import re
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from yeast_phospho import wd
from yeast_phospho.utils import metric
from sklearn.metrics.pairwise import euclidean_distances, manhattan_distances
from sklearn.metrics import roc_curve, auc
from sklearn.linear_model import Lasso
from pandas import DataFrame, read_csv, melt
from scipy.stats.distributions import hypergeom
from pymist.reader.sbml_reader import read_sbml_model


# ---- Calculate metabolite distances
# Import metabolic model mapping
model_met_map = read_csv(wd + 'files/metabolite_mz_map_dobson.txt', sep='\t', index_col='id')
model_met_map['mz'] = [float('%.2f' % i) for i in model_met_map['mz']]
model_met_map = model_met_map.drop_duplicates('mz')['mz'].to_dict()

# Import metabolic model
model = read_sbml_model('/Users/emanuel/Projects/resources/metabolic_models/1752-0509-4-145-s1/yeast_4.04.xml')

# Remove extracellular metabolites
s_matrix = model.get_stoichiometric_matrix()
s_matrix = s_matrix[[not i.endswith('_b') for i in s_matrix.index]]

# Remove highly connected metabolites
met_to_remove = [
    'biomass', 'acetyl-CoA', 'carbon dioxide', 'coenzyme A', 'L-glutamate', 'water', 'hydrogen peroxide',
    'H+', 'NAD(+)', 'NADH', 'NADP(+)', 'NADPH', 'ammonium', 'oxygen', 'phosphate', 'diphosphate', '2-oxoglutarate',
    'acyl-CoA', 'ADP', 'AMP', 'ATP', 'UDP', 'UMP', 'UTP', 'CDP', 'CMP', 'CTP', 'GDP', 'GMP', 'GTP',
    'dADP', 'dAMP', 'dATP', 'dUDP', 'dUMP', 'dUTP', 'dCDP', 'dCMP', 'dCTP', 'dGDP', 'dGMP', 'dGTP'
]
met_to_remove = {k for m in met_to_remove for k, v in model.metabolites.items() if re.match('%s \[.*\]' % re.escape(m), v)}
s_matrix = s_matrix[[i not in met_to_remove for i in s_matrix.index]]

# Remove exchange and biomass reactions
reactions_to_remove = np.hstack((model.get_exchanges(True), 'r_1812'))
s_matrix = s_matrix.loc[:, [r not in reactions_to_remove for r in s_matrix.columns]]

# Get reactions products and substrates
r_substrates = {r: set(s_matrix[s_matrix[r] < 0].index) for r in s_matrix.columns}
r_products = {r: set(s_matrix[s_matrix[r] > 0].index) for r in s_matrix.columns}

# Swap stoichiometric values with ones
s_matrix = (s_matrix != 0) + 0

# Remove un-used metabolites and reactions
s_matrix = s_matrix.loc[:, s_matrix.sum() != 0]
s_matrix = s_matrix[s_matrix.sum(1) != 0]

# Get reactions metabolites
r_metabolites = {r: set(s_matrix.ix[s_matrix[r] != 0, r].index) for r in s_matrix.columns}

# Gene metabolite association
met_reactions = {kegg_id: set(model.s[met_id].keys()) for met_id, kegg_id in model_met_map.items() if met_id in model.s}
gene_reactions = dict(model.get_reactions_by_genes(model.get_genes()).items())

# ---- Read protein interactions dbs
dbs = {}
for bkg_type in ['string', 'phosphogrid']:
    if bkg_type == 'phosphogrid':
        db = read_csv(wd + 'files/PhosphoGrid.txt', sep='\t').loc[:, ['KINASES_ORFS', 'ORF_NAME']]
        db = {(k, r['ORF_NAME']) for i, r in db.iterrows() for k in r['KINASES_ORFS'].split('|') if k != '-'}

    elif bkg_type == 'string':
        db = read_csv(wd + 'files/4932.protein.links.v9.1.txt', sep=' ')
        db_threshold = db['combined_score'].max() * 0.5
        db = db[db['combined_score'] > db_threshold]
        db = {(source.split('.')[1], target.split('.')[1]) for source, target in zip(db['protein1'], db['protein2'])}

    db = {(s, t) for s, t in db if s != t}
    print '[INFO] %s: %d' % (bkg_type, len(db))

    db = {(s, x) for s, t in db for x in [s, t] if x in gene_reactions}
    print '[INFO] %s, only enzyme targets: %d' % (bkg_type, len(db))

    db = {(s, r) for s, t in db for r in gene_reactions[t] if r in s_matrix.columns}
    print '[INFO] %s, only enzymatic reactions: %d' % (bkg_type, len(db))

    db = {(s, m) for s, r in db if r in s_matrix.columns for m in set((s_matrix[s_matrix[r] != 0]).index)}
    print '[INFO] %s, only enzymatic reactions metabolites: %d' % (bkg_type, len(db))

    db = {(s, model_met_map[m]) for s, m in db if m in model_met_map}
    print '[INFO] %s, only measured enzymatic reactions metabolites: %d' % (bkg_type, len(db))

    dbs[bkg_type] = db

db = dbs['string'].union(dbs['phosphogrid'])
print '[INFO] Kinase/Enzymes interactions data-bases imported'

# ---- Import metabolites map
m_map = read_csv('%s/files/metabolite_mz_map_kegg.txt' % wd, sep='\t')
m_map['mz'] = [float('%.2f' % i) for i in m_map['mz']]
m_map = m_map.drop_duplicates('mz').drop_duplicates('formula')
m_map = m_map.groupby('mz')['name'].apply(lambda i: '; '.join(i)).to_dict()

# ---- Import YORF names
acc_name = read_csv('/Users/emanuel/Projects/resources/yeast/yeast_uniprot.txt', sep='\t', index_col=1)['gene'].to_dict()
acc_name = {k: acc_name[k].split(';')[0] for k in acc_name}

# ---- Import data-sets
datasets_files = [
    ('%s/tables/kinase_activity_steady_state.tab' % wd, '%s/tables/metabolomics_steady_state.tab' % wd, 'no_growth'),
    ('%s/tables/kinase_activity_steady_state_with_growth.tab' % wd, '%s/tables/metabolomics_steady_state_growth_rate.tab' % wd, 'with_growth'),
    ('%s/tables/kinase_activity_dynamic.tab' % wd, '%s/tables/metabolomics_dynamic.tab' % wd, 'dynamic')
]

for k_file, m_file, growth in datasets_files:
    # Import kinase activity
    k_activity = read_csv(k_file, sep='\t', index_col=0)
    k_activity = k_activity[(k_activity.count(1) / k_activity.shape[1]) > .75].replace(np.NaN, 0.0)

    # Import metabolomics
    metabolomics = read_csv(m_file, sep='\t', index_col=0).dropna()
    metabolomics = metabolomics[metabolomics.std(1) > .4]

    # Overlapping kinases/phosphatases knockout
    strains = list(set(k_activity.columns).intersection(set(metabolomics.columns)))
    k_activity, metabolomics = k_activity[strains], metabolomics[strains]

    # ---- Correlate metabolic fold-changes with kinase activities
    lm = Lasso(alpha=.01).fit(k_activity.T, metabolomics.T)

    info_table = DataFrame(lm.coef_, index=metabolomics.index, columns=k_activity.index)
    info_table['metabolite'] = info_table.index
    info_table = melt(info_table, id_vars='metabolite', value_name='coef', var_name='kinase')
    info_table = info_table[info_table['coef'] != 0.0]

    info_table['score'] = [info_table['coef'].abs().max() - i for i in info_table['coef'].abs()]

    info_table['kinase_count'] = [k_activity.ix[k].count() for k in info_table['kinase']]

    info_table['metabolite_name'] = [m_map[m] if m in m_map else str(m) for m in info_table['metabolite']]
    info_table['kinase_name'] = [acc_name[k] if k in acc_name else str(k) for k in info_table['kinase']]

    # Kinase/Enzyme interactions via metabolite correlations
    info_table['TP'] = [int(i in db) for i in zip(info_table['kinase'], info_table['metabolite'])]

    # Other metrics
    info_table['euclidean'] = [metric(euclidean_distances, metabolomics.ix[m, strains], k_activity.ix[k, strains])[0][0] for k, m in zip(info_table['kinase'], info_table['metabolite'])]
    info_table['manhattan'] = [metric(manhattan_distances, metabolomics.ix[m, strains], k_activity.ix[k, strains])[0][0] for k, m in zip(info_table['kinase'], info_table['metabolite'])]

    info_table = info_table.dropna()

    info_table.to_csv('%s/tables/kinase_enzyme_enrichment_metabolomics_lm_%s.txt' % (wd, growth), sep='\t')
    print '[INFO] Correaltion between metabolites and kinases done'

    # ---- Kinase/Enzyme enrichment
    int_enrichment, db_proteins = [], {c for i in db for c in i}

    thresholds = roc_curve(info_table['TP'], info_table['score'])[2]

    M = {(k, m) for k, m in set(zip(info_table['kinase'], info_table['metabolite'])) if k in db_proteins}
    n = M.intersection(db)

    for threshold in thresholds:
        N = info_table.loc[info_table['score'] > threshold]
        N = set(zip(N['kinase'], N['metabolite'])).intersection(M)

        x = N.intersection(n)

        fraction = float(len(x)) / float(len(N)) if float(len(N)) != 0.0 else 0
        p_value = hypergeom.sf(len(x), len(M), len(n), len(N))

        int_enrichment.append((threshold, fraction, p_value, len(M), len(n), len(N), len(x)))

    int_enrichment = DataFrame(int_enrichment, columns=['thres', 'fraction', 'pvalue', 'M', 'n', 'N', 'x']).dropna()
    print '[INFO] Kinase/Enzyme enrichment ready'

    # ---- Plot Kinase/Enzyme enrichment
    sns.set(style='ticks', palette='pastel', color_codes=True)
    (f, enrichemnt_plot) = plt.subplots(1, 2, figsize=(10, 5))

    # ROC plot analysis
    ax = enrichemnt_plot[0]

    for roc_metric in ['euclidean', 'manhattan', 'score']:
        curve_fpr, curve_tpr, thresholds = roc_curve(info_table['TP'], info_table[roc_metric])
        curve_auc = auc(curve_fpr, curve_tpr)

        ax.plot(curve_fpr, curve_tpr, label='%s (area = %0.2f)' % (roc_metric, curve_auc))

    ax.plot([0, 1], [0, 1], 'k--')
    ax.set_xlabel('False Positive Rate')
    ax.set_ylabel('True Positive Rate')
    sns.despine(trim=True, ax=ax)
    ax.legend(loc='lower right')

    # Hypergeometric specific thresold analysis
    ax = enrichemnt_plot[1]

    plot_df = int_enrichment[['thres', 'fraction']].copy()
    plot_df = plot_df[plot_df['fraction'] != 0]

    ax.plot(plot_df['thres'], plot_df['fraction'], c='gray')
    ax.set_xlim(plot_df['thres'].min(), plot_df['thres'].max())
    ax.set_ylim(plot_df['fraction'].min(), plot_df['fraction'].max())
    ax.set_xlabel('Threshold')
    ax.set_ylabel('Fraction')
    sns.despine(ax=ax)

    plt.savefig('%s/reports/kinase_enzyme_enrichment_metabolomics_lm_%s.pdf' % (wd, growth), bbox_inches='tight')
    plt.close('all')
    print '[INFO] Plotting done: %s/reports/kinase_enzyme_enrichment_metabolomics_%s.pdf' % (wd, growth)
