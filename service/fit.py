# ===============================================================================
# Copyright (C) 2010 Diego Duclos
#
# This file is part of pyfa.
#
# pyfa is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyfa is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyfa.  If not, see <http://www.gnu.org/licenses/>.
# ===============================================================================

import copy
from logbook import Logger
from time import time

import eos.db
from eos.saveddata.booster import Booster as es_Booster
from eos.saveddata.cargo import Cargo as es_Cargo
from eos.saveddata.character import Character as saveddata_Character
from eos.saveddata.citadel import Citadel as es_Citadel
from eos.saveddata.damagePattern import DamagePattern as es_DamagePattern
from eos.saveddata.drone import Drone as es_Drone
from eos.saveddata.fighter import Fighter as es_Fighter
from eos.saveddata.implant import Implant as es_Implant
from eos.saveddata.ship import Ship as es_Ship
from eos.saveddata.module import Module as es_Module, State, Slot
from eos.saveddata.fit import Fit as FitType
from service.character import Character
from service.damagePattern import DamagePattern
from service.settings import SettingsProvider

pyfalog = Logger(__name__)


class Fit(object):
    instance = None

    @classmethod
    def getInstance(cls):
        if cls.instance is None:
            cls.instance = Fit()

        return cls.instance

    def __init__(self):
        pyfalog.debug("Initialize Fit class")
        self.cached_fits = []
        self.pattern = DamagePattern.getInstance().getDamagePattern("Uniform")
        self.targetResists = None
        self.character = saveddata_Character.getAll5()
        self.booster = False

        serviceFittingDefaultOptions = {
            "useGlobalCharacter"    : False,
            "useGlobalDamagePattern": False,
            "defaultCharacter"      : self.character.ID,
            "useGlobalForceReload"  : False,
            "colorFitBySlot"        : False,
            "rackSlots"             : True,
            "rackLabels"            : True,
            "compactSkills"         : True,
            "showTooltip"           : True,
            "showMarketShortcuts"   : False,
            "enableGaugeAnimation"  : True,
            "exportCharges"         : True,
            "openFitInNew"          : False,
            "priceSystem"           : "Jita",
            "showShipBrowserTooltip": True,
        }

        self.serviceFittingOptions = SettingsProvider.getInstance().getSettings(
                "pyfaServiceFittingOptions", serviceFittingDefaultOptions)

    @staticmethod
    def getAllFits():
        pyfalog.debug("Fetching all fits")
        fits = eos.db.getFitList()
        return fits

    @staticmethod
    def getFitsWithShip(shipID):
        """ Lists fits of shipID, used with shipBrowser """
        pyfalog.debug("Fetching all fits for ship ID: {0}", shipID)
        fits = eos.db.getFitsWithShip(shipID)
        names = []
        for fit in fits:
            names.append((fit.ID, fit.name, fit.booster, fit.timestamp))

        return names

    @staticmethod
    def getFitsWithModules(typeIDs):
        """ Lists fits flagged as booster """
        fits = eos.db.getFitsWithModules(typeIDs)
        return fits

    @staticmethod
    def countAllFits():
        pyfalog.debug("Getting count of all fits.")
        return eos.db.countAllFits()

    @staticmethod
    def countFitsWithShip(stuff):
        pyfalog.debug("Getting count of all fits for: {0}", stuff)
        count = eos.db.countFitsWithShip(stuff)
        return count

    def getModule(self, fitID, pos):
        fit = self.getFit(fitID, basic=True)
        return fit.modules[pos]

    def newFit(self, shipID, name=None):
        pyfalog.debug("Creating new fit for ID: {0}", shipID)
        try:
            ship = es_Ship(eos.db.getItem(shipID))
        except ValueError:
            ship = es_Citadel(eos.db.getItem(shipID))
        fit = FitType(ship)
        fit.name = name if name is not None else "New %s" % fit.ship.item.name
        fit.damagePattern = self.pattern
        fit.targetResists = self.targetResists
        fit.character = self.character
        fit.booster = self.booster
        eos.db.save(fit)
        self.recalc(fit)
        return fit.ID

    def toggleBoostFit(self, fitID):
        pyfalog.debug("Toggling as booster for fit ID: {0}", fitID)
        fit = self.getFit(fitID, basic=True)
        fit.booster = not fit.booster
        eos.db.commit()

    def renameFit(self, fitID, newName):
        pyfalog.debug("Renaming fit ({0}) to: {1}", fitID, newName)
        fit = self.getFit(fitID, basic=True)
        fit.name = newName
        eos.db.commit()

    def deleteFit(self, fitID):
        pyfalog.debug("Deleting fit for fit ID: {0}", fitID)
        fit = self.getFit(fitID, basic=True)

        eos.db.remove(fit)

        # refresh any fits this fit is projected onto. Otherwise, if we have
        # already loaded those fits, they will not reflect the changes
        for projection in fit.projectedOnto.values():
            if projection.victim_fit in eos.db.saveddata_session:  # GH issue #359
                eos.db.saveddata_session.refresh(projection.victim_fit)

    def copyFit(self, fitID):
        pyfalog.debug("Creating copy of fit ID: {0}", fitID)
        fit = self.getFit(fitID, basic=True)
        newFit = copy.deepcopy(fit)
        eos.db.save(newFit)
        return newFit.ID

    def clearFit(self, fitID):
        pyfalog.debug("Clearing fit for fit ID: {0}", fitID)
        if fitID is None:
            return None

        fit = self.getFit(fitID)
        fit.clear()
        return fit

    def toggleFactorReload(self, fitID):
        pyfalog.debug("Toggling factor reload for fit ID: {0}", fitID)
        if fitID is None:
            return None

        fit = self.getFit(fitID, basic=True)
        fit.factorReload = not fit.factorReload
        self.recalc(fit, withBoosters=False)

    def switchFit(self, fitID):
        pyfalog.debug("Switching fit to fit ID: {0}", fitID)
        if fitID is None:
            return None

        force_recalc = False
        fit = self.getFit(fitID)

        if self.serviceFittingOptions["useGlobalCharacter"]:
            if fit.character != self.character:
                fit.character = self.character
                force_recalc = True

        if self.serviceFittingOptions["useGlobalDamagePattern"]:
            if fit.damagePattern != self.pattern:
                fit.damagePattern = self.pattern
                force_recalc = True

        if not fit.calculated or force_recalc:
            self.recalc(fit)

    def getFit(self, fitID, basic=False):
        """
        Gets fit from database
        """
        pyfalog.debug("Getting fit for fit ID: {0}", fitID)
        if fitID is None:
            return None

        fit = next((x for x in self.cached_fits if x.ID == fitID), None)

        if fit is None:
            fit = eos.db.getFit(fitID)

        if basic:
            return fit

            fit.inited = True

        if fit:
            # Check that the states of all modules are valid
            self.checkStates(fit, None)
            fit.fill()

            if not fit.calculated:
                self.recalc(fit)

            return fit
        else:
            return None

    @staticmethod
    def searchFits(name):
        pyfalog.debug("Searching for fit: {0}", name)
        results = eos.db.searchFits(name)
        fits = []
        for fit in results:
            fits.append((
                fit.ID, fit.name, fit.ship.item.ID, fit.ship.item.name, fit.booster,
                fit.timestamp))
        return fits

    def addImplant(self, fitID, itemID, recalc=True):
        pyfalog.debug("Adding implant to fit ({0}) for item ID: {1}", fitID, itemID)
        if fitID is None:
            return False

        fit = self.getFit(fitID)
        item = eos.db.getItem(itemID, eager="attributes")
        try:
            implant = es_Implant(item)
        except ValueError:
            pyfalog.warning("Invalid item: {0}", itemID)
            return False

        fit.implants.append(implant)
        if recalc:
            self.recalc(fit, withBoosters=False)
        return True

    def removeImplant(self, fitID, position):
        pyfalog.debug("Removing implant from position ({0}) for fit ID: {1}", position, fitID)
        if fitID is None:
            return False

        fit = self.getFit(fitID)
        implant = fit.implants[position]
        fit.implants.remove(implant)
        self.recalc(fit, withBoosters=False)
        return True

    def addBooster(self, fitID, itemID):
        pyfalog.debug("Adding booster ({0}) to fit ID: {1}", itemID, fitID)
        if fitID is None:
            return False

        fit = self.getFit(fitID)
        item = eos.db.getItem(itemID, eager="attributes")
        try:
            booster = es_Booster(item)
        except ValueError:
            pyfalog.warning("Invalid item: {0}", itemID)
            return False

        fit.boosters.append(booster)
        self.recalc(fit, withBoosters=False)
        return True

    def removeBooster(self, fitID, position):
        pyfalog.debug("Removing booster from position ({0}) for fit ID: {1}", position, fitID)
        if fitID is None:
            return False

        fit = self.getFit(fitID)
        booster = fit.boosters[position]
        fit.boosters.remove(booster)
        self.recalc(fit, withBoosters=False)
        return True

    def project(self, fitID, thing):
        pyfalog.debug("Projecting fit ({0}) onto: {1}", fitID, thing)
        if fitID is None:
            return

        fit = self.getFit(fitID, basic=True)

        if isinstance(thing, int):
            thing = eos.db.getItem(thing,
                                   eager=("attributes", "group.category"))

        if isinstance(thing, FitType):
            if thing in fit.projectedFits:
                return

            fit.__projectedFits[thing.ID] = thing

            # this bit is required -- see GH issue # 83
            eos.db.saveddata_session.flush()
            eos.db.saveddata_session.refresh(thing)
        elif thing.category.name == "Drone":
            drone = None
            for d in fit.projectedDrones.find(thing):
                if d is None or d.amountActive == d.amount or d.amount >= 5:
                    drone = d
                    break

            if drone is None:
                drone = es_Drone(thing)
                fit.projectedDrones.append(drone)

            drone.amount += 1
        elif thing.category.name == "Fighter":
            fighter = es_Fighter(thing)
            fit.projectedFighters.append(fighter)
        elif thing.group.name == "Effect Beacon":
            module = es_Module(thing)
            module.state = State.ONLINE
            fit.projectedModules.append(module)
        else:
            module = es_Module(thing)
            module.state = State.ACTIVE
            if not module.canHaveState(module.state, fit):
                module.state = State.OFFLINE
            fit.projectedModules.append(module)

        self.recalc(fit)
        return True

    def addCommandFit(self, fitID, thing):
        pyfalog.debug("Projecting command fit ({0}) onto: {1}", fitID, thing)
        if fitID is None:
            return

        fit = self.getFit(fitID, basic=True)

        if thing in fit.commandFits:
            return

        fit.__commandFits[thing.ID] = thing

        # this bit is required -- see GH issue # 83
        eos.db.saveddata_session.flush()
        eos.db.saveddata_session.refresh(thing)

        self.recalc(fit)
        return True

    def toggleProjected(self, fitID, thing, click):
        pyfalog.debug("Toggling projected on fit ({0}) for: {1}", fitID, thing)
        fit = self.getFit(fitID, basic=True)
        if isinstance(thing, es_Drone):
            if thing.amountActive == 0 and thing.canBeApplied(fit):
                thing.amountActive = thing.amount
            else:
                thing.amountActive = 0
        elif isinstance(thing, es_Fighter):
            thing.active = not thing.active
        elif isinstance(thing, es_Module):
            thing.state = self.__getProposedState(thing, click)
            if not thing.canHaveState(thing.state, fit):
                thing.state = State.OFFLINE
        elif isinstance(thing, FitType):
            projectionInfo = thing.getProjectionInfo(fitID)
            if projectionInfo:
                projectionInfo.active = not projectionInfo.active

        self.recalc(fit)

    def toggleCommandFit(self, fitID, thing):
        pyfalog.debug("Toggle command fit ({0}) for: {1}", fitID, thing)
        fit = self.getFit(fitID, basic=True)
        commandInfo = thing.getCommandInfo(fitID)
        if commandInfo:
            commandInfo.active = not commandInfo.active

        self.recalc(fit)

    def changeAmount(self, fitID, projected_fit, amount):
        """Change amount of projected fits"""
        pyfalog.debug("Changing fit ({0}) for projected fit ({1}) to new amount: {2}", fitID, projected_fit.getProjectionInfo(fitID), amount)
        fit = self.getFit(fitID, basic=True)
        amount = min(20, max(1, amount))  # 1 <= a <= 20
        projectionInfo = projected_fit.getProjectionInfo(fitID)
        if projectionInfo:
            projectionInfo.amount = amount

        self.recalc(fit)

    def changeActiveFighters(self, fitID, fighter, amount):
        pyfalog.debug("Changing active fighters ({0}) for fit ({1}) to amount: {2}", fighter.itemID, fitID, amount)
        fit = self.getFit(fitID, basic=True)
        fighter.amountActive = amount

        self.recalc(fit, withBoosters=False)

    def removeProjected(self, fitID, thing):
        pyfalog.debug("Removing projection on fit ({0}) from: {1}", fitID, thing)
        fit = self.getFit(fitID, basic=True)
        if isinstance(thing, es_Drone):
            fit.projectedDrones.remove(thing)
        elif isinstance(thing, es_Module):
            fit.projectedModules.remove(thing)
        elif isinstance(thing, es_Fighter):
            fit.projectedFighters.remove(thing)
        else:
            del fit.__projectedFits[thing.ID]
            # fit.projectedFits.remove(thing)

        self.recalc(fit)

    def removeCommand(self, fitID, thing):
        pyfalog.debug("Removing command projection from fit ({0}) for: {1}", fitID, thing)
        fit = self.getFit(fitID, basic=True)
        del fit.__commandFits[thing.ID]

        self.recalc(fit)

    def appendModule(self, fitID, itemID):
        pyfalog.debug("Appending module for fit ({0}) using item: {1}", fitID, itemID)
        fit = self.getFit(fitID, basic=True)
        item = eos.db.getItem(itemID, eager=("attributes", "group.category"))
        try:
            m = es_Module(item)
        except ValueError:
            pyfalog.warning("Invalid item: {0}", itemID)
            return False

        if m.item.category.name == "Subsystem":
            fit.modules.freeSlot(m.getModifiedItemAttr("subSystemSlot"))

        if m.fits(fit):
            m.owner = fit
            numSlots = len(fit.modules)
            fit.modules.append(m)
            if m.isValidState(State.ACTIVE):
                m.state = State.ACTIVE

            # As some items may affect state-limiting attributes of the ship, calculate new attributes first
            self.recalc(fit)
            # Then, check states of all modules and change where needed. This will recalc if needed
            self.checkStates(fit, m)

            fit.fill()
            eos.db.commit()

            return numSlots != len(fit.modules)
        else:
            return None

    def removeModule(self, fitID, position):
        pyfalog.debug("Removing module from position ({0}) for fit ID: {1}", position, fitID)
        fit = self.getFit(fitID, basic=True)
        if fit.modules[position].isEmpty:
            return None

        numSlots = len(fit.modules)
        fit.modules.toDummy(position)
        self.recalc(fit)
        self.checkStates(fit, None)
        fit.fill()
        eos.db.commit()
        return numSlots != len(fit.modules)

    def changeModule(self, fitID, position, newItemID):
        pyfalog.debug("Changing position of module from position ({0}) for fit ID: {1}", position, fitID)
        fit = self.getFit(fitID, basic=True)

        # Dummy it out in case the next bit fails
        fit.modules.toDummy(position)

        item = eos.db.getItem(newItemID, eager=("attributes", "group.category"))
        try:
            m = es_Module(item)
        except ValueError:
            pyfalog.warning("Invalid item: {0}", newItemID)
            return False

        if m.fits(fit):
            m.owner = fit
            fit.modules.toModule(position, m)
            if m.isValidState(State.ACTIVE):
                m.state = State.ACTIVE

            # As some items may affect state-limiting attributes of the ship, calculate new attributes first
            self.recalc(fit)
            # Then, check states of all modules and change where needed. This will recalc if needed
            self.checkStates(fit, m)

            fit.fill()
            eos.db.commit()

            return True
        else:
            return None

    def moveCargoToModule(self, fitID, moduleIdx, cargoIdx, copyMod=False):
        """
        Moves cargo to fitting window. Can either do a copy, move, or swap with current module
        If we try to copy/move into a spot with a non-empty module, we swap instead.
        To avoid redundancy in converting Cargo item, this function does the
        sanity checks as opposed to the GUI View. This is different than how the
        normal .swapModules() does things, which is mostly a blind swap.
        """
        pyfalog.debug("Moving cargo item to module for fit ID: {1}", fitID)
        fit = self.getFit(fitID, basic=True)

        module = fit.modules[moduleIdx]
        cargo = fit.cargo[cargoIdx]

        # Gather modules and convert Cargo item to Module, silently return if not a module
        try:
            cargoP = es_Module(cargo.item)
            cargoP.owner = fit
            if cargoP.isValidState(State.ACTIVE):
                cargoP.state = State.ACTIVE
        except:
            pyfalog.warning("Invalid item: {0}", cargo.item)
            return

        if cargoP.slot != module.slot:  # can't swap modules to different racks
            return

        # remove module that we are trying to move cargo to
        fit.modules.remove(module)

        if not cargoP.fits(fit):  # if cargo doesn't fit, rollback and return
            fit.modules.insert(moduleIdx, module)
            return

        fit.modules.insert(moduleIdx, cargoP)

        if not copyMod:  # remove existing cargo if not cloning
            if cargo.amount == 1:
                fit.cargo.remove(cargo)
            else:
                cargo.amount -= 1

        if not module.isEmpty:  # if module is placeholder, we don't want to convert/add it
            for x in fit.cargo.find(module.item):
                x.amount += 1
                break
            else:
                moduleP = es_Cargo(module.item)
                moduleP.amount = 1
                fit.cargo.insert(cargoIdx, moduleP)

        self.recalc(fit)

    def swapModules(self, fitID, src, dst):
        pyfalog.debug("Swapping modules from source ({0}) to destination ({1}) for fit ID: {1}", src, dst, fitID)
        fit = self.getFit(fitID, basic=True)
        # Gather modules
        srcMod = fit.modules[src]
        dstMod = fit.modules[dst]

        # To swap, we simply remove mod and insert at destination.
        fit.modules.remove(srcMod)
        fit.modules.insert(dst, srcMod)
        fit.modules.remove(dstMod)
        fit.modules.insert(src, dstMod)

        eos.db.commit()

    def cloneModule(self, fitID, src, dst):
        """
        Clone a module from src to dst
        This will overwrite dst! Checking for empty module must be
        done at a higher level
        """
        pyfalog.debug("Cloning modules from source ({0}) to destination ({1}) for fit ID: {1}", src, dst, fitID)
        fit = self.getFit(fitID)
        # Gather modules
        srcMod = fit.modules[src]
        dstMod = fit.modules[dst]  # should be a placeholder module

        new = copy.deepcopy(srcMod)
        new.owner = fit
        if new.fits(fit):
            # insert copy if module meets hardpoint restrictions
            fit.modules.remove(dstMod)
            fit.modules.insert(dst, new)

            self.recalc(fit)

    def addCargo(self, fitID, itemID, amount=1, replace=False):
        """
        Adds cargo via typeID of item. If replace = True, we replace amount with
        given parameter, otherwise we increment
        """
        pyfalog.debug("Adding cargo ({0}) fit ID: {1}", itemID, fitID)

        if fitID is None:
            return False

        fit = self.getFit(fitID, basic=True)
        item = eos.db.getItem(itemID)
        cargo = None

        # adding from market
        for x in fit.cargo.find(item):
            if x is not None:
                # found item already in cargo, use previous value and remove old
                cargo = x
                fit.cargo.remove(x)
                break

        if cargo is None:
            # if we don't have the item already in cargo, use default values
            cargo = es_Cargo(item)

        fit.cargo.append(cargo)
        if replace:
            cargo.amount = amount
        else:
            cargo.amount += amount

        self.recalc(fit, withBoosters=False)

        return True

    def removeCargo(self, fitID, position):
        pyfalog.debug("Removing cargo from position ({0}) fit ID: {1}", position, fitID)
        if fitID is None:
            return False

        fit = self.getFit(fitID)
        charge = fit.cargo[position]
        fit.cargo.remove(charge)
        self.recalc(fit, withBoosters=False)
        return True

    def addFighter(self, fitID, itemID):
        pyfalog.debug("Adding fighters ({0}) to fit ID: {1}", itemID, fitID)
        if fitID is None:
            return False

        fit = self.getFit(fitID, basic=True)
        item = eos.db.getItem(itemID, eager=("attributes", "group.category"))
        if item.category.name == "Fighter":
            fighter = None
            '''
            for d in fit.fighters.find(item):
                if d is not None and d.amountActive == 0 and d.amount < max(5, fit.extraAttributes["maxActiveDrones"]):
                    drone = d
                    break
            '''
            if fighter is None:
                fighter = es_Fighter(item)
                used = fit.getSlotsUsed(fighter.slot)
                total = fit.getNumSlots(fighter.slot)
                standardAttackActive = False
                for ability in fighter.abilities:
                    if ability.effect.isImplemented and ability.effect.handlerName == u'fighterabilityattackm':
                        # Activate "standard attack" if available
                        ability.active = True
                        standardAttackActive = True
                    else:
                        # Activate all other abilities (Neut, Web, etc) except propmods if no standard attack is active
                        if ability.effect.isImplemented and standardAttackActive is False and ability.effect.handlerName != u'fighterabilitymicrowarpdrive' and \
                                        ability.effect.handlerName != u'fighterabilityevasivemaneuvers':
                            ability.active = True

                if used >= total:
                    fighter.active = False

                if fighter.fits(fit) is True:
                    fit.fighters.append(fighter)
                else:
                    return False

            self.recalc(fit, withBoosters=False)
            return True
        else:
            return False

    def removeFighter(self, fitID, i):
        pyfalog.debug("Removing fighters from fit ID: {0}", fitID)
        fit = self.getFit(fitID, basic=True)
        f = fit.fighters[i]
        fit.fighters.remove(f)

        self.recalc(fit, withBoosters=False)
        return True

    def addDrone(self, fitID, itemID, numDronesToAdd=1):
        pyfalog.debug("Adding {0} drones ({1}) to fit ID: {2}", numDronesToAdd, itemID, fitID)
        if fitID is None:
            return False

        fit = self.getFit(fitID, basic=True)
        item = eos.db.getItem(itemID, eager=("attributes", "group.category"))
        if item.category.name == "Drone":
            drone = None
            for d in fit.drones.find(item):
                if d is not None and d.amountActive == 0 and d.amount < max(5, fit.extraAttributes["maxActiveDrones"]):
                    drone = d
                    break

            if drone is None:
                drone = es_Drone(item)
                if drone.fits(fit) is True:
                    fit.drones.append(drone)
                else:
                    return False
            drone.amount += numDronesToAdd
            self.recalc(fit, withBoosters=False)
            return True
        else:
            return False

    def mergeDrones(self, fitID, d1, d2, projected=False):
        pyfalog.debug("Merging drones on fit ID: {0}", fitID)
        if fitID is None:
            return False

        fit = self.getFit(fitID, basic=True)
        if d1.item != d2.item:
            return False

        if projected:
            fit.projectedDrones.remove(d1)
        else:
            fit.drones.remove(d1)

        d2.amount += d1.amount
        d2.amountActive += d1.amountActive

        # If we have less than the total number of drones active, make them all active. Fixes #728
        # This could be removed if we ever add an enhancement to make drone stacks partially active.
        if d2.amount > d2.amountActive:
            d2.amountActive = d2.amount

        self.recalc(fit, withBoosters=False)
        return True

    @staticmethod
    def splitDrones(fit, d, amount, l):
        pyfalog.debug("Splitting drones for fit ID: {0}", fit)
        total = d.amount
        active = d.amountActive > 0
        d.amount = amount
        d.amountActive = amount if active else 0

        newD = es_Drone(d.item)
        newD.amount = total - amount
        newD.amountActive = newD.amount if active else 0
        l.append(newD)
        eos.db.commit()

    def splitProjectedDroneStack(self, fitID, d, amount):
        pyfalog.debug("Splitting projected drone stack for fit ID: {0}", fitID)
        if fitID is None:
            return False

        fit = self.getFit(fitID)
        self.splitDrones(fit, d, amount, fit.projectedDrones)

    def splitDroneStack(self, fitID, d, amount):
        pyfalog.debug("Splitting drone stack for fit ID: {0}", fitID)
        if fitID is None:
            return False

        fit = self.getFit(fitID)
        self.splitDrones(fit, d, amount, fit.drones)

    def removeDrone(self, fitID, i, numDronesToRemove=1):
        pyfalog.debug("Removing {0} drones for fit ID: {1}", numDronesToRemove, fitID)
        fit = self.getFit(fitID, basic=True)
        d = fit.drones[i]
        d.amount -= numDronesToRemove
        if d.amountActive > 0:
            d.amountActive -= numDronesToRemove

        if d.amount == 0:
            del fit.drones[i]

        self.recalc(fit, withBoosters=False)
        return True

    def toggleDrone(self, fitID, i):
        pyfalog.debug("Toggling drones for fit ID: {0}", fitID)
        fit = self.getFit(fitID, basic=True)
        d = fit.drones[i]
        if d.amount == d.amountActive:
            d.amountActive = 0
        else:
            d.amountActive = d.amount

        self.recalc(fit, withBoosters=False)
        return True

    def toggleFighter(self, fitID, i):
        pyfalog.debug("Toggling fighters for fit ID: {0}", fitID)
        fit = self.getFit(fitID, basic=True)
        f = fit.fighters[i]
        f.active = not f.active

        self.recalc(fit, withBoosters=False)
        return True

    def toggleImplant(self, fitID, i):
        pyfalog.debug("Toggling implant for fit ID: {0}", fitID)
        fit = self.getFit(fitID, basic=True)
        implant = fit.implants[i]
        implant.active = not implant.active

        self.recalc(fit, withBoosters=False)
        return True

    def toggleImplantSource(self, fitID, source):
        pyfalog.debug("Toggling implant source for fit ID: {0}", fitID)
        fit = self.getFit(fitID, basic=True)
        fit.implantSource = source

        self.recalc(fit, withBoosters=False)
        return True

    def toggleBooster(self, fitID, i):
        pyfalog.debug("Toggling booster for fit ID: {0}", fitID)
        fit = self.getFit(fitID, basic=True)
        booster = fit.boosters[i]
        booster.active = not booster.active

        self.recalc(fit, withBoosters=False)
        return True

    def toggleFighterAbility(self, fitID, ability):
        pyfalog.debug("Toggling fighter ability for fit ID: {0}", fitID)
        fit = self.getFit(fitID, basic=True)
        ability.active = not ability.active

        self.recalc(fit, withBoosters=False)

    def changeChar(self, fitID, charID):
        if fitID is None:
            return

        if charID is None:
            # Default to the all5 char
            charID = Character.getInstance().all5().ID

        pyfalog.debug("Changing character ({0}) for fit ID: {1}", charID, fitID)

        fit = self.getFit(fitID)
        fit.character = self.character = eos.db.getCharacter(charID)
        self.recalc(fit)

    @staticmethod
    def isAmmo(itemID):
        return eos.db.getItem(itemID).category.name == "Charge"

    def setAmmo(self, fitID, ammoID, modules):
        pyfalog.debug("Set ammo for fit ID: {0}", fitID)
        if fitID is None:
            return

        fit = self.getFit(fitID)
        ammo = eos.db.getItem(ammoID) if ammoID else None

        for mod in modules:
            if mod.isValidCharge(ammo):
                mod.charge = ammo

        self.recalc(fit)

    def getTargetResists(self, fitID):
        pyfalog.debug("Get target resists for fit ID: {0}", fitID)
        if fitID is None:
            return

        fit = self.getFit(fitID)
        return fit.targetResists

    def setTargetResists(self, fitID, pattern):
        pyfalog.debug("Set target resist for fit ID: {0}", fitID)
        if fitID is None:
            return

        fit = self.getFit(fitID, basic=True)
        fit.targetResists = pattern

        self.recalc(fit, withBoosters=False)

    def getDamagePattern(self, fitID):
        pyfalog.debug("Get damage pattern for fit ID: {0}", fitID)
        if fitID is None:
            return

        fit = self.getFit(fitID)
        return fit.damagePattern

    def setDamagePattern(self, fitID, pattern):
        pyfalog.debug("Set damage pattern for fit ID: {0}", fitID)
        if fitID is None:
            return

        fit = self.getFit(fitID, basic=True)
        fit.damagePattern = self.pattern = pattern

        self.recalc(fit, withBoosters=False)

    def setMode(self, fitID, mode):
        pyfalog.debug("Set mode for fit ID: {0}", fitID)
        if fitID is None:
            return

        fit = self.getFit(fitID, basic=True)
        fit.mode = mode

        self.recalc(fit)

    def setAsPattern(self, fitID, ammo):
        pyfalog.debug("Set as pattern for fit ID: {0}", fitID)
        if fitID is None:
            return

        sDP = DamagePattern.getInstance()
        dp = sDP.getDamagePattern("Selected Ammo")
        if dp is None:
            dp = es_DamagePattern()
            dp.name = "Selected Ammo"

        fit = self.getFit(fitID)
        for attr in ("em", "thermal", "kinetic", "explosive"):
            setattr(dp, "%sAmount" % attr, ammo.getAttribute("%sDamage" % attr) or 0)

        fit.damagePattern = dp
        self.recalc(fit, withBoosters=False)

    def checkStates(self, fit, base):
        pyfalog.debug("Check states for fit ID: {0}", fit)
        changed = False
        for mod in fit.modules:
            if mod != base:
                # fix for #529, where a module may be in incorrect state after CCP changes mechanics of module
                if not mod.canHaveState(mod.state) or not mod.isValidState(mod.state):
                    mod.state = State.ONLINE
                    changed = True

        for mod in fit.projectedModules:
            # fix for #529, where a module may be in incorrect state after CCP changes mechanics of module
            if not mod.canHaveState(mod.state, fit) or not mod.isValidState(mod.state):
                mod.state = State.OFFLINE
                changed = True

        for drone in fit.projectedDrones:
            if drone.amountActive > 0 and not drone.canBeApplied(fit):
                drone.amountActive = 0
                changed = True

        # If any state was changed, recalculate attributes again
        if changed:
            self.recalc(fit)

    def toggleModulesState(self, fitID, base, modules, click):
        pyfalog.debug("Toggle module state for fit ID: {0}", fitID)
        changed = False
        proposedState = self.__getProposedState(base, click)

        if proposedState != base.state:
            changed = True
            base.state = proposedState
            for mod in modules:
                if mod != base:
                    p = self.__getProposedState(mod, click, proposedState)
                    mod.state = p
                    if p != mod.state:
                        changed = True

        if changed:
            fit = self.getFit(fitID)

            # As some items may affect state-limiting attributes of the ship, calculate new attributes first
            self.recalc(fit)
            # Then, check states of all modules and change where needed. This will recalc if needed
            self.checkStates(fit, base)

    # Old state : New State
    localMap = {
        State.OVERHEATED: State.ACTIVE,
        State.ACTIVE    : State.ONLINE,
        State.OFFLINE   : State.ONLINE,
        State.ONLINE    : State.ACTIVE
    }
    projectedMap = {
        State.OVERHEATED: State.ACTIVE,
        State.ACTIVE    : State.OFFLINE,
        State.OFFLINE   : State.ACTIVE,
        State.ONLINE    : State.ACTIVE
    }  # Just in case
    # For system effects. They should only ever be online or offline
    projectedSystem = {
        State.OFFLINE: State.ONLINE,
        State.ONLINE : State.OFFLINE
    }

    def __getProposedState(self, mod, click, proposedState=None):
        pyfalog.debug("Get proposed state for module.")
        if mod.slot == Slot.SUBSYSTEM or mod.isEmpty:
            return State.ONLINE

        if mod.slot == Slot.SYSTEM:
            transitionMap = self.projectedSystem
        else:
            transitionMap = self.projectedMap if mod.projected else self.localMap

        currState = mod.state

        if proposedState is not None:
            state = proposedState
        elif click == "right":
            state = State.OVERHEATED
        elif click == "ctrl":
            state = State.OFFLINE
        else:
            state = transitionMap[currState]
            if not mod.isValidState(state):
                state = -1

        if mod.isValidState(state):
            return state
        else:
            return currState

    def recalc(self, fit, withBoosters=True):
        start_time = time()
        pyfalog.info("=" * 10 + "recalc: {0}" + "=" * 10, fit.name)

        # Commit any changes before we recalc
        fit.clear()
        eos.db.commit()

        if fit.factorReload is not self.serviceFittingOptions["useGlobalForceReload"]:
            fit.factorReload = self.serviceFittingOptions["useGlobalForceReload"]

        if withBoosters:
            for projected_fit in fit.projectedFits:
                if projected_fit is not self:
                    # Cache the fit to speed up processing later
                    self.getFit(projected_fit.ID, basic=True)
            for command_fit in fit.commandFits:
                if command_fit is not self:
                    # Cache the fit to speed up processing later
                    self.getFit(command_fit.ID, basic=True)

        # Disabled in 08be50c. Not sure why?
        fit.calculateFitAttributes(withBoosters=withBoosters)

        if fit not in self.cached_fits:
            self.cached_fits.append(fit)

        pyfalog.info("=" * 10 + "recalc time: " + str(time() - start_time) + "=" * 10)
