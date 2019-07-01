/*
 * Copyright (c) 2017 - 2018 Memorial Sloan-Kettering Cancer Center.
 *
 * This library is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY, WITHOUT EVEN THE IMPLIED WARRANTY OF
 * MERCHANTABILITY OR FITNESS FOR A PARTICULAR PURPOSE.  The software and
 * documentation provided hereunder is on an "as is" basis, and
 * Memorial Sloan-Kettering Cancer Center
 * has no obligations to provide maintenance, support,
 * updates, enhancements or modifications.  In no event shall
 * Memorial Sloan-Kettering Cancer Center
 * be liable to any party for direct, indirect, special,
 * incidental or consequential damages, including lost profits, arising
 * out of the use of this software and its documentation, even if
 * Memorial Sloan-Kettering Cancer Center
 * has been advised of the possibility of such damage.
*/

package org.mskcc.oncotree.crosswalk;

import org.mskcc.oncotree.error.*;
import java.util.*;
import javax.annotation.PostConstruct;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.mskcc.oncotree.topbraid.OncoTreeNode;
import org.mskcc.oncotree.topbraid.OncoTreeRepository;
import org.mskcc.oncotree.topbraid.OncoTreeVersionRepository;
import org.mskcc.oncotree.topbraid.TopBraidException;
import org.mskcc.oncotree.utils.FailedCacheRefreshException;
import org.mskcc.oncotree.utils.OncoTreePersistentCache;
import org.mskcc.oncotree.model.Version;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;

/**
 *
 * @author Manda Wilson
 **/
@Component
@EnableScheduling
public class MSKConceptCache {

    private static final Logger logger = LoggerFactory.getLogger(MSKConceptCache.class);

    @Autowired
    private OncoTreePersistentCache oncoTreePersistentCache;

    // this only gets called when the main tumor types cache gets refreshed
    // refresh the MSKConceptCache as well
    // this gets called by tumorTypesUtil - but when it gets called it's looping through versions and calling for 
    // every node in every version 
    // add another function that only updates on the first iteration (e.g if it updates for version 2017-11, don't update on later loops when it searches for 2018-12)
    public MSKConcept get(String oncoTreeCode) {
        MSKConcept concept = new MSKConcept();
        boolean failedUpdateMskConceptInPersistentCache = false;
        try {
            oncoTreePersistentCache.updateMSKConceptInPersistentCache(oncoTreeCode);
        } catch (CrosswalkException e) {
            failedUpdateMskConceptInPersistentCache = true;
        }
        try {
            concept = oncoTreePersistentCache.getMSKConceptFromPersistentCache(oncoTreeCode); 
        } catch (CrosswalkException e) {
            try {
                concept = oncoTreePersistentCache.getMSKConceptFromPersistentCacheBackup(oncoTreeCode);
                if (concept == null) {
                    return new MSKConcept();
                }
            } catch (Exception e2) {
                return new MSKConcept();
            }                       
        }
        if (!failedUpdateMskConceptInPersistentCache) {
            try {
                oncoTreePersistentCache.backupMSKConceptPersistentCache(concept, oncoTreeCode);
            } catch (Exception e) {
                logger.error("Unable to backup MSKConcpet EHCache for the following:" + concept + " <---------> " + oncoTreeCode + "\n\n\n");
                logger.error(e.getMessage());
                logger.error("\n======================== ERROR MESSAGE =============================\n");
                e.printStackTrace();
            }
        }
        return concept;
    }
}
