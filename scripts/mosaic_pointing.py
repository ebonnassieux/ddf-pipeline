#!/usr/bin/env python

# intended as a one-stop shop for mosaicing
# contains some of the same arguments as mosaic.py
import argparse
from find_mosaic_pointings import read_pointingfile, find_pointings_to_mosaic
import os
from auxcodes import getpos,getposim,dotdict
import glob
from mosaic import make_mosaic
from astropy.io import fits
import numpy as np
import pickle
try:
    import bdsf as bdsm
except ImportError:
    import lofar.bdsm as bdsm

if __name__=='__main__':
    parser = argparse.ArgumentParser(description='Mosaic LoTSS pointings')
    parser.add_argument('--directories', metavar='D', nargs='+',
                        help='directories to search for pipeline output')
    parser.add_argument('--beamcut', dest='beamcut', default=0.3, help='Beam level to cut at')
    parser.add_argument('--no-check',dest='no_check', action='store_true', help='Do not check for missing images')
    parser.add_argument('pointingfile', type=str, help='LoTSS pointing progress file')
    parser.add_argument('mospointingname', type=str, help='Mosaic central pointing name')
    
    args = parser.parse_args()
    pointingfilename = args.pointingfile
    mospointingname = args.mospointingname
    pointingdict = read_pointingfile(pointingfilename)
    print 'Now searching for results directories'

    cwd=os.getcwd()
    # basic process pinched from plot_dir_pos
    results=[]
    for d in args.directories:
        os.chdir(d)
        mss=glob.glob('*.ms')
        if len(mss)>0:
            name,ra,dec=getpos(mss[1])
            results.append([d,name,ra,dec])
        else:
            ims=glob.glob('image_full_ampphase1m_shift.int.facetRestored.fits')
            if len(ims)>0:
                ra,dec=getposim(ims[0])
                name=d.split('/')[-1]
                name=name.split('_')[0]
                results.append([d,name,ra,dec])

    os.chdir(cwd)
    # find what we need to put in the mosaic
    mosaicpointings,mosseps = find_pointings_to_mosaic(pointingdict,args.mospointingname)
    maxsep=np.max(mosseps)
    # now find whether we have got these pointings somewhere!
    mosaicdirs=[]
    missingpointing = False
    for p in mosaicpointings:
        print 'Wanting to put pointing %s in mosiac'%p
        _,ra,dec,_=pointingdict[p]
        for r in results:
            rd,rname,rra,rdec=r
            if name==p:
                # name match
                mosaicdirs.append(rd)
                break
            elif ((ra-rra)**2.0+(dec-rdec)**2.0)<0.05:
                mosaicdirs.append(rd)
                break
        else:
            print 'Pointing',p,'not found'
            missingpointing = True
            
    if not(args.no_check) and missingpointing == True:
        raise RuntimeError('Failed to find a required pointing')

    print 'Mosaicing using directories', mosaicdirs

    # now construct the inputs for make_mosaic

    mos_args=dotdict({'save':True, 'load':True,'exact':False,'use_shifted':True,'find_noise':True})
    mos_args.beamcut=args.beamcut
    mos_args.directories=mosaicdirs
    
    # construct template FITS header
    restfrq=143.65e6
    header=fits.Header()
    size=(maxsep/2.0)*1.1
    cellsize=1.5/3600.0
    himsize=int(size/cellsize)
    header['SIMPLE']=True
    header['BITPIX']=-32
    header['NAXIS']=2
    header['WCSAXES']=2
    header['NAXIS1']=2*himsize
    header['NAXIS2']=2*himsize
    header['CTYPE1']='RA---SIN'
    header['CTYPE2']='DEC--SIN'
    header['CUNIT1']='deg'
    header['CUNIT2']='deg'
    header['CRPIX1']=himsize
    header['CRPIX2']=himsize
    header['CRVAL1']=pointingdict[args.mospointingname][1]
    header['CRVAL2']=pointingdict[args.mospointingname][2]
    header['CDELT1']=-cellsize
    header['CDELT2']=cellsize
    header['RADESYS']='ICRS'
    header['EQUINOX']=2000.0
    header['LONPOLE']=180.0
    header['LATPOLE']=header['CRVAL2']
    header['BMAJ']=4.0*cellsize
    header['BMIN']=4.0*cellsize
    header['BPA']=0
    header['TELESCOP']='LOFAR'
    header['RESTFRQ']=restfrq
    header['OBSERVER']='LoTSS'
    mos_args.header=header
    print 'Calling make_mosaic'
    with open('mosaic-header.pickle','w') as f:
        pickle.dump(header,f)

    make_mosaic(mos_args)

    print 'Blanking the mosaic...'

    hdu=fits.open('mosaic.fits')
    x=np.array(range(0,2*himsize))
    xv, yv = np.meshgrid(x, x)
    xv-=himsize
    yv-=himsize
    hdu[0].data[np.sqrt(xv**2.0+yv**2.0)>himsize]=np.nan
    hdu.writeto('mosaic-blanked.fits', clobber=True)

    print 'Now running PyBDSF to extract sources'
    
    catprefix='mosaic'
    img = bdsm.process_image('mosaic-blanked.fits', thresh_isl=4.0, thresh_pix=5.0, rms_box=(160,50), rms_map=True, mean_map='zero', ini_method='intensity', adaptive_rms_box=True, adaptive_thresh=150, rms_box_bright=(60,15), group_by_isl=False, group_tol=10.0,output_opts=True, output_all=True, atrous_do=True,atrous_jmax=4, flagging_opts=True, flag_maxsize_fwhm=0.5,advanced_opts=True, blank_limit=None,frequency=restfrq)
    img.write_catalog(outfile=catprefix +'.cat.fits',catalog_type='srl',format='fits',correct_proj='True')
    img.export_image(outfile=catprefix +'.rms.fits',img_type='rms',img_format='fits',clobber=True)
    img.export_image(outfile=catprefix +'.resid.fits',img_type='gaus_resid',img_format='fits',clobber=True)
    img.export_image(outfile=catprefix +'.pybdsmmask.fits',img_type='island_mask',img_format='fits',clobber=True)
    img.write_catalog(outfile=catprefix +'.cat.reg',catalog_type='srl',format='ds9',correct_proj='True')
