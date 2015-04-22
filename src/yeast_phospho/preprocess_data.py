import re
import numpy as np
from pandas import read_csv, Index


def get_site(protein, peptide):
    pep_start = protein.find(re.sub('\[.+\]', '', peptide))
    pep_site_strat = peptide.find('[')
    site_pos = pep_start + pep_site_strat
    return protein[site_pos - 1] + str(site_pos)

wd = '/Users/emanuel/Projects/projects/yeast_phospho/'

# Import Phosphogrid network
network = read_csv(wd + 'files/phosphosites.txt', sep='\t').loc[:, ['ORF_NAME', 'PHOSPHO_SITE', 'KINASES_ORFS', 'PHOSPHATASES_ORFS', 'SEQUENCE']]
print '[INFO] [PHOSPHOGRID] ', network.shape

####  Process steady-state phosphoproteomics
phospho_df = read_csv(wd + 'files/phosphoproteomics/allEvents.tsv', sep='\t')
phospho_df = phospho_df.pivot_table(values='logFC', index=['peptide', 'target'], columns='regulator', aggfunc=np.median)
print '[INFO] [PHOSPHOPROTEOMICS] merge repeated phosphopeptides, i.e. median : ', phospho_df.shape

# Consider phoshopeptides with only one phosphosite
phospho_df = phospho_df.loc[[len(re.findall('\[[0-9]*\.?[0-9]*\]', peptide)) == 1 for peptide in phospho_df.index.levels[0]]]
print '[INFO] [PHOSPHOPROTEOMICS] (filtered phosphopetides with multiple phosphosites): ', phospho_df.shape

# Remove K and R aminoacids from the peptide head
phospho_df.index = phospho_df.index.set_levels([re.split('^[K|R]\.', x)[1] for x in phospho_df.index.levels[0]], 'peptide')

# Match peptide sequences to protein sequence and calculate peptide phosphorylation site
pep_match = {peptide: set(network.loc[network['ORF_NAME'] == target, 'SEQUENCE']) for (peptide, target), r in phospho_df.iterrows()}
pep_site = {peptide: target + '_' + get_site(list(pep_match[peptide])[0].upper(), peptide) for (peptide, target), r in phospho_df.iterrows() if len(pep_match[peptide]) == 1}

# Merge phosphosites with median
phospho_df['site'] = [pep_site[peptide] if peptide in pep_site else np.NaN for (peptide, target), r in phospho_df.iterrows()]
phospho_df = phospho_df.groupby('site').median()
print '[INFO] [PHOSPHOPROTEOMICS] (merge phosphosites, i.e median): ', phospho_df.shape

# Export processed data-set
phospho_df_file = wd + 'tables/steady_state_phosphoproteomics.tab'
phospho_df.to_csv(phospho_df_file, sep='\t')
print '[INFO] [PHOSPHOPROTEOMICS] Exported to: %s' % phospho_df_file

#### Process steady-state metabolomics
metabol_df = read_csv(wd + 'files/metabolomics/Table_S3.txt', sep='\t')
metabol_df.index = Index(metabol_df['m/z'], dtype=np.str)
print '[INFO] [METABOLOMICS]: ', metabol_df.shape

metabol_df = metabol_df.drop('m/z', 1).dropna()
print '[INFO] [METABOLOMICS] drop NaN: ', metabol_df.shape

fc_thres, n_fc_thres = 1.0, 1
metabol_df = metabol_df[(metabol_df.abs() > fc_thres).sum(1) > n_fc_thres]
print '[INFO] [METABOLOMICS] drop metabolites with less than %d abs FC higher than %.2f : ' % (n_fc_thres, fc_thres), metabol_df.shape

# Export processed data-set
metabol_df_file = wd + 'tables/steady_state_metabolomics.tab'
metabol_df.to_csv(metabol_df_file, sep='\t')
print '[INFO] [METABOLOMICS] Exported to: %s' % metabol_df_file